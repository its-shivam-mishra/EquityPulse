import os
import re as _re
import math
import shutil
import time
import tempfile
from pathlib import Path
import pandas as pd
import yfinance as yf
from azure.communication.email import EmailClient
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


# Workspace asset path configuration
ASSETS_DIR = Path("assets")
EXCEL_PATH = ASSETS_DIR / "stocks.xlsx"
COMPANY_NAME_CACHE_FILE = ASSETS_DIR / "company_names.json"
COLUMNS = ["Company Name", "Stock Code", "Exchange", "Buying Price", "Quantity", "Tag", "Buy Date", "Row Color", "_ts"]

def get_company_name(ticker_obj, symbol: str) -> str:
    import json
    cache = {}
    if COMPANY_NAME_CACHE_FILE.exists():
        try:
            with open(COMPANY_NAME_CACHE_FILE, "r") as f:
                cache = json.load(f)
        except Exception:
            pass
            
    if symbol in cache:
        return cache[symbol]
        
    try:
        # Avoid blocking significantly if possible, but info is a property that makes a request
        name = ticker_obj.info.get('longName') or ticker_obj.info.get('shortName') or symbol
        cache[symbol] = name
        with open(COMPANY_NAME_CACHE_FILE, "w") as f:
            json.dump(cache, f)
        return name
    except Exception:
        return symbol

def ensure_excel_file():
    """Ensure assets folder and Excel file exist with correct structure."""
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    if not EXCEL_PATH.exists():
        # Create empty excel file with columns
        df = pd.DataFrame(columns=COLUMNS)
        df.to_excel(EXCEL_PATH, index=False)
        print(f"Created default Excel file at {EXCEL_PATH.resolve()}")

def read_stocks(username: str) -> pd.DataFrame:
    """Read stocks from Cosmos DB for a specific user."""
    from app.cosmos_service import cosmos_service
    try:
        items = cosmos_service.get_all_stocks(username)
        if not items:
            return pd.DataFrame(columns=COLUMNS)
            
        df = pd.DataFrame(items)
        
        # Ensure correct columns exist
        for col in COLUMNS:
            if col not in df.columns:
                df[col] = None
        
        # Clean data
        df = df.dropna(subset=["Stock Code"])
        df["Company Name"] = df["Company Name"].astype(str).str.strip()
        df["Stock Code"] = df["Stock Code"].astype(str).str.strip().str.upper()
        df["Exchange"] = df["Exchange"].astype(str).str.strip().str.upper()
        df["Buying Price"] = pd.to_numeric(df["Buying Price"], errors="coerce").fillna(0.0)
        df["Quantity"] = pd.to_numeric(df["Quantity"], errors="coerce").fillna(0.0)
        df["Tag"] = df["Tag"].astype(str).str.strip()
        return df[COLUMNS]
    except Exception as e:
        print(f"Error reading from Cosmos DB: {e}")
        return pd.DataFrame(columns=COLUMNS)

def write_stocks(df: pd.DataFrame, username: str):
    """Write DataFrame of stocks back to Cosmos DB for a user."""
    from app.cosmos_service import cosmos_service
    # Format
    df["Company Name"] = df["Company Name"].astype(str).str.strip()
    df["Stock Code"] = df["Stock Code"].astype(str).str.strip().str.upper()
    df["Exchange"] = df["Exchange"].astype(str).str.strip().str.upper()
    df["Buying Price"] = pd.to_numeric(df["Buying Price"], errors="coerce").fillna(0.0)
    df["Quantity"] = pd.to_numeric(df["Quantity"], errors="coerce").fillna(0.0)

    # Upsert each row to Cosmos DB
    for _, row in df.iterrows():
        stock_code = row["Stock Code"]
        exchange = row["Exchange"]
        if not stock_code:
            continue
            
        stock_item = {
            "Company Name": row["Company Name"],
            "Stock Code": stock_code,
            "Exchange": exchange,
            "Buying Price": row["Buying Price"],
            "Quantity": row["Quantity"],
            "Tag": row.get("Tag"),
            "Buy Date": row.get("Buy Date")
        }
        cosmos_service.upsert_stock(stock_item, username)

# NSE trade-segment suffixes that Yahoo Finance does not recognise.
# These are administrative markers (Trade-to-Trade, suspended, SME, etc.)
# and must be stripped from the base ticker before querying yfinance.
_NSE_SEGMENT_MARKERS = _re.compile(r'-(?:T|X|BE|N|SM|ST)$', _re.IGNORECASE)

def format_symbol(symbol: str) -> str:
    """Format symbol to ensure it is NSE/BSE compatible with yfinance.

    Handles three cases:
    1. Symbol already has .NS / .BO exchange suffix — strip any NSE segment
       marker from the base (e.g. DEEDEV-T.NS → DEEDEV.NS) and return.
    2. Plain ticker with no dot — strip segment marker, append .NS.
    3. Any other dotted form — return as-is.

    NSE segment markers (-T, -X, -BE, -N, -SM) are administrative labels used
    by exchanges that Yahoo Finance does not support as part of a ticker symbol.
    """
    sym = symbol.strip().upper()

    if sym.endswith(".NS") or sym.endswith(".BO"):
        # Split off the exchange suffix, clean the base, reattach
        base, exchange = sym.rsplit(".", 1)
        base = _NSE_SEGMENT_MARKERS.sub("", base)
        return f"{base}.{exchange}"

    if "." not in sym:
        # Plain ticker — strip marker, default to NSE
        base = _NSE_SEGMENT_MARKERS.sub("", sym)
        return f"{base}.NS"

    # Already has some other suffix — return as-is
    return sym

def _fetch_ticker_history_with_retry(ticker, period="1y", retries=3, delay=1.0):
    for attempt in range(retries):
        try:
            hist = ticker.history(period=period)
            if not hist.empty:
                return hist
        except Exception as e:
            if attempt == retries - 1:
                print(f"Failed to fetch history for {ticker.ticker} after {retries} attempts: {e}")
            else:
                time.sleep(delay)
    return pd.DataFrame()

def get_stock_data(symbol: str):
    """
    Fetch stock metadata: current price and SMA 20, 50, 100, 200.
    Returns: (current_price, sma20, sma50, sma100, sma200, actual_symbol, today_change, today_change_pct, company_name)
    """
    formatted_symbol = format_symbol(symbol)
    ticker = yf.Ticker(formatted_symbol)
    
    # We query historical data for past 1 year (approx 250 trading days)
    # to calculate moving averages, using the retry mechanism.
    hist = _fetch_ticker_history_with_retry(ticker, period="1y")
    
    # Automatic exchange fallback (NSE <-> BSE) if no historical data found
    if hist.empty:
        fallback_symbol = None
        if formatted_symbol.endswith(".NS"):
            fallback_symbol = formatted_symbol[:-3] + ".BO"
        elif formatted_symbol.endswith(".BO"):
            fallback_symbol = formatted_symbol[:-3] + ".NS"
            
        if fallback_symbol:
            fallback_ticker = yf.Ticker(fallback_symbol)
            fallback_hist = _fetch_ticker_history_with_retry(fallback_ticker, period="1y")
            if not fallback_hist.empty:
                formatted_symbol = fallback_symbol
                ticker = fallback_ticker
                hist = fallback_hist

    if hist.empty:
        # FALLBACK: Try to get just the current price and previous close from fast_info if history fails
        try:
            if hasattr(ticker, 'fast_info') and getattr(ticker.fast_info, 'last_price', None) is not None:
                current_price = float(ticker.fast_info.last_price)
                prev_price = float(getattr(ticker.fast_info, 'previous_close', current_price))
                today_change = current_price - prev_price
                today_change_pct = (today_change / prev_price) * 100 if prev_price > 0 else 0.0
                company_name = get_company_name(ticker, formatted_symbol)
                return current_price, None, None, None, None, formatted_symbol, today_change, today_change_pct, company_name
        except Exception as e:
            print(f"Fallback to fast_info failed for {formatted_symbol}: {e}")
            
        raise ValueError(f"Ticker '{formatted_symbol}' returned no historical data. Please verify the stock symbol.")
    
    close_prices = hist["Close"].copy()
    
    # If today's close is NaN (market open but no close yet), try to get the live real-time price
    if pd.isna(close_prices.iloc[-1]):
        try:
            live_price = None
            if hasattr(ticker, 'fast_info'):
                live_price = ticker.fast_info.last_price
            
            if live_price is not None and not math.isnan(live_price):
                close_prices.iloc[-1] = float(live_price)
        except Exception:
            pass

    # Drop any remaining NaN values to ensure valid calculation
    close_prices = close_prices.dropna()
    if close_prices.empty:
        raise ValueError(f"Ticker '{formatted_symbol}' returned no valid price data.")
    current_price = float(close_prices.iloc[-1])
    
    # Calculate simple moving averages
    sma20 = float(close_prices.rolling(window=20).mean().iloc[-1]) if len(close_prices) >= 20 else None
    sma50 = float(close_prices.rolling(window=50).mean().iloc[-1]) if len(close_prices) >= 50 else None
    sma100 = float(close_prices.rolling(window=100).mean().iloc[-1]) if len(close_prices) >= 100 else None
    sma200 = float(close_prices.rolling(window=200).mean().iloc[-1]) if len(close_prices) >= 200 else None
    
    # Optional fallback for SMA if not enough data points
    if sma20 is not None and math.isnan(sma20):
        sma20 = None
    if sma50 is not None and math.isnan(sma50):
        sma50 = None
    if sma100 is not None and math.isnan(sma100):
        sma100 = None
    if sma200 is not None and math.isnan(sma200):
        sma200 = None

    # Calculate today's change relative to previous close
    try:
        if hasattr(ticker, 'fast_info') and ticker.fast_info.previous_close is not None:
            prev_price = float(ticker.fast_info.previous_close)
            today_change = current_price - prev_price
            today_change_pct = (today_change / prev_price) * 100
        else:
            raise ValueError("No fast_info")
    except Exception:
        if len(close_prices) >= 2:
            prev_price = float(close_prices.iloc[-2])
            today_change = current_price - prev_price
            today_change_pct = (today_change / prev_price) * 100
        else:
            today_change = 0.0
            today_change_pct = 0.0

    company_name = get_company_name(ticker, formatted_symbol)

    return current_price, sma20, sma50, sma100, sma200, formatted_symbol, today_change, today_change_pct, company_name

def get_stock_history(symbol: str, period: str = "1y"):
    """
    Fetch historical prices and SMAs for plotting.
    Returns lists of dates, close prices, sma20, sma50, sma100, sma200.
    """
    formatted_symbol = format_symbol(symbol)
    ticker = yf.Ticker(formatted_symbol)
    hist = _fetch_ticker_history_with_retry(ticker, period=period)
    
    # Automatic exchange fallback (NSE <-> BSE) if no historical data found
    if hist.empty:
        fallback_symbol = None
        if formatted_symbol.endswith(".NS"):
            fallback_symbol = formatted_symbol[:-3] + ".BO"
        elif formatted_symbol.endswith(".BO"):
            fallback_symbol = formatted_symbol[:-3] + ".NS"
            
        if fallback_symbol:
            fallback_ticker = yf.Ticker(fallback_symbol)
            fallback_hist = _fetch_ticker_history_with_retry(fallback_ticker, period=period)
            if not fallback_hist.empty:
                formatted_symbol = fallback_symbol
                ticker = fallback_ticker
                hist = fallback_hist

    if hist.empty:
        raise ValueError(f"Ticker '{formatted_symbol}' returned no historical data.")
    
    # Calculate SMAs for all points
    hist["SMA_20"] = hist["Close"].rolling(window=20).mean()
    hist["SMA_50"] = hist["Close"].rolling(window=50).mean()
    hist["SMA_100"] = hist["Close"].rolling(window=100).mean()
    hist["SMA_200"] = hist["Close"].rolling(window=200).mean()
    
    # Calculate Bollinger Bands
    std_20 = hist["Close"].rolling(window=20).std()
    hist["BB_Upper"] = hist["SMA_20"] + (std_20 * 2)
    hist["BB_Lower"] = hist["SMA_20"] - (std_20 * 2)
    
    # Calculate RSI (14-period)
    delta = hist["Close"].diff()
    gain = delta.where(delta > 0, 0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss
    hist["RSI"] = 100 - (100 / (1 + rs))
    
    # Extract Latest News
    news_data = []
    try:
        raw_news = ticker.news
        if raw_news:
            for item in raw_news[:4]:  # Top 4 news items
                news_data.append({
                    "title": item.get("content", {}).get("title", "No Title"),
                    "link": item.get("content", {}).get("clickThroughUrl", {}).get("url", "#"),
                    "publisher": item.get("content", {}).get("provider", {}).get("displayName", "Unknown"),
                    "time": item.get("content", {}).get("pubDate", "")
                })
    except Exception:
        pass
    
    # Reset index to get Date
    hist = hist.reset_index()
    
    # Handle timezone if present
    if pd.api.types.is_datetime64tz_dtype(hist["Date"]):
        dates = hist["Date"].dt.strftime("%Y-%m-%d").tolist()
    else:
        dates = hist["Date"].dt.strftime("%Y-%m-%d").tolist()
        
    closes = hist["Close"].ffill().tolist()
    sma20_list = hist["SMA_20"].bfill().tolist()
    sma50_list = hist["SMA_50"].bfill().tolist()
    sma100_list = hist["SMA_100"].bfill().tolist()
    sma200_list = hist["SMA_200"].bfill().tolist()
    bb_upper_list = hist["BB_Upper"].bfill().tolist()
    bb_lower_list = hist["BB_Lower"].bfill().tolist()
    rsi_list = hist["RSI"].bfill().tolist()
    
    def sanitize(lst):
        return [None if (isinstance(x, float) and math.isnan(x)) else x for x in lst]

    # ── Company Info ─────────────────────────────────────────────────────────
    # Fetch rich metadata from yfinance .info for the About Company panel.
    # All fields use .get() with None fallback so missing data never raises.
    company_info = {}
    try:
        info = ticker.info or {}

        def _safe(key):
            val = info.get(key)
            if isinstance(val, float) and math.isnan(val):
                return None
            return val

        company_info = {
            "longName":             _safe("longName") or _safe("shortName") or formatted_symbol,
            "longBusinessSummary":  _safe("longBusinessSummary"),
            "sector":               _safe("sector"),
            "industry":             _safe("industry"),
            "website":              _safe("website"),
            "city":                 _safe("city"),
            "state":                _safe("state"),
            "country":              _safe("country"),
            "fullTimeEmployees":    _safe("fullTimeEmployees"),
            # Valuation
            "marketCap":            _safe("marketCap"),
            "trailingPE":           _safe("trailingPE"),
            "forwardPE":            _safe("forwardPE"),
            "priceToBook":          _safe("priceToBook"),
            "enterpriseValue":      _safe("enterpriseValue"),
            "trailingEps":          _safe("trailingEps"),
            # Dividend & yield
            "dividendYield":        _safe("dividendYield"),
            "dividendRate":         _safe("dividendRate"),
            # Risk
            "beta":                 _safe("beta"),
            # 52-week range
            "fiftyTwoWeekHigh":     _safe("fiftyTwoWeekHigh"),
            "fiftyTwoWeekLow":      _safe("fiftyTwoWeekLow"),
            "fiftyDayAverage":      _safe("fiftyDayAverage"),
            "twoHundredDayAverage": _safe("twoHundredDayAverage"),
            # Volume
            "averageVolume":        _safe("averageVolume"),
            "regularMarketVolume":  _safe("regularMarketVolume"),
            # Revenue / Profitability
            "totalRevenue":         _safe("totalRevenue"),
            "grossMargins":         _safe("grossMargins"),
            "profitMargins":        _safe("profitMargins"),
            "returnOnEquity":       _safe("returnOnEquity"),
            "debtToEquity":         _safe("debtToEquity"),
        }
    except Exception as e:
        print(f"[company_info] Failed to fetch info for {formatted_symbol}: {e}")

    return {
        "dates": dates,
        "prices": sanitize(closes),
        "sma20": sanitize(sma20_list),
        "sma50": sanitize(sma50_list),
        "sma100": sanitize(sma100_list),
        "sma200": sanitize(sma200_list),
        "bb_upper": sanitize(bb_upper_list),
        "bb_lower": sanitize(bb_lower_list),
        "rsi": sanitize(rsi_list),
        "news": news_data,
        "symbol": formatted_symbol,
        "company_info": company_info
    }

def get_all_stocks_with_metrics(username: str) -> list:
    """Read stocks from Cosmos DB and enrich with real-time yfinance metrics."""
    df = read_stocks(username)
    results = []
    
    for _, row in df.iterrows():
        company_name_db = str(row["Company Name"]).strip()
        stock_code = str(row["Stock Code"]).strip().upper()
        exchange = str(row["Exchange"]).strip().upper()
        buying_price = float(row["Buying Price"])
        quantity = float(row["Quantity"])
        tag = str(row.get("Tag", "")).strip()
        row_color_raw = row.get("Row Color", None)
        row_color = str(row_color_raw).strip() if row_color_raw and str(row_color_raw).strip() not in ("", "nan", "None") else None
        
        # Build symbol for yfinance
        suffix = ".NS" if exchange == "NSE" else ".BO" if exchange == "BSE" else ""
        symbol = f"{stock_code}{suffix}"
        
        try:
            current_price, sma20, sma50, sma100, sma200, actual_symbol, today_change, today_change_pct, fetched_company_name = get_stock_data(symbol)
            
            import pytz
            from datetime import datetime
            
            ist = pytz.timezone('Asia/Kolkata')
            today_str = datetime.now(ist).strftime('%Y-%m-%d')
            
            buy_date = str(row.get("Buy Date", ""))
            ts = row.get("_ts")
            
            is_bought_today = False
            if buy_date == today_str:
                is_bought_today = True
            elif buy_date in ["nan", "None", "", "NaT"]:
                if pd.notna(ts):
                    ts_date = datetime.fromtimestamp(ts, tz=pytz.utc).astimezone(ist).strftime('%Y-%m-%d')
                    # Fallback for stocks added before Buy Date was introduced
                    if ts_date == today_str and current_price > 0:
                        if abs(current_price - buying_price) / current_price < 0.10:
                            is_bought_today = True

            if is_bought_today and buying_price > 0:
                today_change = current_price - buying_price
                today_change_pct = (today_change / buying_price) * 100

            investment_value = buying_price * quantity
            current_value = current_price * quantity
            gain_loss = current_value - investment_value
            gain_loss_pct = ((current_price - buying_price) / buying_price * 100) if buying_price > 0 else 0.0
            today_return_val = today_change * quantity
            
            def clean_nan(val):
                return None if (isinstance(val, float) and math.isnan(val)) else val

            results.append({
                "company_name": company_name_db or fetched_company_name,
                "stock_code": stock_code,
                "exchange": exchange,
                "symbol": symbol,
                "display_symbol": actual_symbol,
                "buying_price": clean_nan(buying_price),
                "quantity": clean_nan(quantity),
                "current_price": clean_nan(current_price),
                "sma20": clean_nan(sma20),
                "sma50": clean_nan(sma50),
                "sma100": clean_nan(sma100),
                "sma200": clean_nan(sma200),
                "investment_value": clean_nan(investment_value),
                "current_value": clean_nan(current_value),
                "gain_loss": clean_nan(gain_loss),
                "gain_loss_pct": clean_nan(gain_loss_pct),
                "today_change": clean_nan(today_change),
                "today_change_pct": clean_nan(today_change_pct),
                "today_return_val": clean_nan(today_return_val),
                "tag": tag if tag and tag.lower() != "nan" else None,
                "row_color": row_color,
                "status": "success",
                "error": None
            })
        except Exception as e:
            # Fallback in case a ticker fetch fails, return it with error details
            results.append({
                "company_name": company_name_db or stock_code,
                "stock_code": stock_code,
                "exchange": exchange,
                "symbol": symbol,
                "display_symbol": symbol,
                "buying_price": buying_price,
                "quantity": quantity,
                "current_price": None,
                "sma20": None,
                "sma50": None,
                "sma100": None,
                "sma200": None,
                "investment_value": buying_price * quantity,
                "current_value": None,
                "gain_loss": None,
                "gain_loss_pct": None,
                "today_change": None,
                "today_change_pct": None,
                "today_return_val": None,
                "tag": tag if tag and tag.lower() != "nan" else None,
                "row_color": row_color,
                "status": "error",
                "error": str(e)
            })
            
    return results

def add_stock(company_name: str, stock_code: str, exchange: str, price: float, quantity: float, username: str, tag: str = None) -> dict:
    """
    Add a stock transaction directly to Cosmos DB for a user.
    """
    from app.cosmos_service import cosmos_service
    stock_code_upper = stock_code.strip().upper()
    exchange_upper = exchange.strip().upper()
    suffix = ".NS" if exchange_upper == "NSE" else ".BO" if exchange_upper == "BSE" else ""
    raw_symbol = f"{stock_code_upper}{suffix}"
    symbol = format_symbol(raw_symbol)
    
    # Extract the base stock code after formatting (e.g., removing -SM)
    stock_code_upper = symbol.rsplit(".", 1)[0] if "." in symbol else symbol

    
    existing = cosmos_service.get_stock(symbol, exchange_upper, username)
    
    from datetime import datetime
    import pytz
    ist = pytz.timezone('Asia/Kolkata')
    today_str = datetime.now(ist).strftime('%Y-%m-%d')
    
    if existing:
        old_price = float(existing.get("Buying Price", 0))
        old_qty = float(existing.get("Quantity", 0))
        
        total_qty = old_qty + quantity
        avg_price = (old_price * old_qty + price * quantity) / total_qty if total_qty > 0 else 0.0
            
        existing["Buying Price"] = avg_price
        existing["Quantity"] = total_qty
        existing["Company Name"] = company_name.strip()
        if tag is not None:
            existing["Tag"] = tag.strip()
            
        # If they add more quantity today, we could potentially set Buy Date to today if it's the first addition,
        # but existing means it's a merge. We keep original Buy Date.
        if "Buy Date" not in existing:
            existing["Buy Date"] = today_str
            
        cosmos_service.upsert_stock(existing, username)
        action = "merged"
    else:
        new_item = {
            "Company Name": company_name.strip(),
            "Stock Code": stock_code_upper,
            "Exchange": exchange_upper,
            "Buying Price": price,
            "Quantity": quantity,
            "Tag": tag.strip() if tag else None,
            "Buy Date": today_str,
            "id": symbol
        }
        cosmos_service.upsert_stock(new_item, username)
        action = "added"
        
    return {"stock_code": stock_code_upper, "action": action}

def update_stock(symbol: str, price: float, quantity: float, new_company_name: str = None, new_stock_code: str = None, new_exchange: str = None, username: str = None, tag: str = None) -> dict:
    """Directly update price, quantity, and optionally company name, stock code, and exchange in Cosmos DB for a user."""
    from app.cosmos_service import cosmos_service
    formatted_symbol = format_symbol(symbol).upper()
    exchange = "NSE" if formatted_symbol.endswith(".NS") else "BSE" if formatted_symbol.endswith(".BO") else "NSE"
    
    existing = cosmos_service.get_stock(formatted_symbol, exchange, username)
            
    if not existing:
        raise KeyError(f"Stock '{formatted_symbol}' not found in portfolio.")
        
    existing["Buying Price"] = price
    existing["Quantity"] = quantity
    
    if new_company_name:
        existing["Company Name"] = new_company_name.strip()
        
    if tag is not None:
        existing["Tag"] = tag.strip()
        
    if new_stock_code or new_exchange:
        old_exchange = existing["Exchange"]
        old_id = existing["id"]
        
        if new_stock_code:
            existing["Stock Code"] = new_stock_code.strip().upper()
        if new_exchange:
            existing["Exchange"] = new_exchange.strip().upper()
            
        new_suffix = ".NS" if existing["Exchange"] == "NSE" else ".BO" if existing["Exchange"] == "BSE" else ""
        new_id = f"{username}_{existing['Stock Code']}{new_suffix}"
        existing["id"] = new_id
        
        cosmos_service.delete_stock(old_id, old_exchange, username)
        cosmos_service.upsert_stock(existing, username)
    else:
        cosmos_service.upsert_stock(existing, username)
    
    return {"stock_code": existing["Stock Code"], "action": "updated"}

def delete_stock(symbol: str, username: str) -> dict:
    """Delete a stock from Cosmos DB for a user."""
    from app.cosmos_service import cosmos_service
    formatted_symbol = format_symbol(symbol).upper()
    exchange = "NSE" if formatted_symbol.endswith(".NS") else "BSE" if formatted_symbol.endswith(".BO") else "NSE"
    
    success = cosmos_service.delete_stock(formatted_symbol, exchange, username)
    if not success:
        raise KeyError(f"Stock '{formatted_symbol}' not found in portfolio.")
        
    return {"symbol": formatted_symbol, "action": "deleted"}

def _check_portfolio_writable():
    """No-op for Cosmos DB as it handles concurrent writes gracefully."""
    pass


# ---------------------------------------------------------------------------
# Shared Excel → DataFrame parser (handles multiple real-world file formats)
# ---------------------------------------------------------------------------

# Canonical column aliases: lowercase alias → standard internal name
_COLUMN_ALIASES: dict[str, str] = {
    # Stock identifier (symbol/ticker)
    "stock code":           "Stock Code",
    "stock":                "Stock Code",
    "ticker":               "Stock Code",
    "symbol":               "Stock Code",
    "scrip":                "Stock Code",
    "code":                 "Stock Code",
    # Company / stock full name (Layout C — ISIN-only broker exports)
    "company name":         "Company Name",
    "company":              "Company Name",
    "name":                 "Company Name",
    "stock name":           "Company Name",   # e.g. Motilal / Sharekhan statements
    # ISIN — preserved so we can resolve to a ticker when no symbol column exists
    "isin":                 "ISIN",
    # Exchange
    "exchange":             "Exchange",
    "market":               "Exchange",
    # Buying / average price
    "buying price":         "Buying Price",
    "buy price":            "Buying Price",
    "price":                "Buying Price",
    "avg price":            "Buying Price",
    "average price":        "Buying Price",
    "average buy price":    "Buying Price",   # e.g. Motilal holdings statement
    # Quantity held
    "quantity":             "Quantity",
    "qty":                  "Quantity",
    "shares":               "Quantity",
    # Broker-format extras (IndiaInfoline / Groww style)
    "quantity available":   "Quantity",   # broker format — tradeable qty
    "quantity discrepant":  None,          # ignored
    "quantity long term":   None,          # ignored
    "quantity pledged (margin)": None,     # ignored
    "quantity pledged (loan)":   None,     # ignored
    "sector":               None,          # ignored
    "instrument type":      None,          # ignored
    "previous closing price": None,        # ignored
    "closing price":        None,          # ignored
    "closing value":        None,          # ignored
    "buy value":            None,          # ignored
    "unrealized p&l":       None,          # ignored
    "unrealised p&l":       None,          # ignored
    "unrealize p&l pct.":   None,          # ignored
    "unrealized p&l pct.":  None,          # ignored
    "unique client code":   None,          # ignored
}

_REQUIRED_FIELDS = ["Stock Code", "Buying Price", "Quantity"]


def _parse_price(val) -> float | None:
    """Parse a price value: strip commas, ₹ signs, spaces → float."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        cleaned = str(val).replace(",", "").replace("\u20b9", "").replace(" ", "").strip()
        if not cleaned or cleaned.lower() == "nan" or cleaned == "-":
            return None
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def _parse_qty(val) -> int | None:
    """Parse a quantity value: strip commas/spaces → int."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        cleaned = str(val).replace(",", "").replace(" ", "").strip()
        if not cleaned or cleaned.lower() == "nan" or cleaned == "-":
            return None
        return round(float(cleaned))
    except (ValueError, TypeError):
        return None


def _map_columns(columns: list[str]) -> dict[str, str]:
    """
    Build a rename map from raw column names → standard names.
    Returns a dict {original_col: standard_col} for columns we care about.
    """
    headers_map: dict[str, str] = {}
    for col in columns:
        alias = str(col).strip().lower()
        if alias in _COLUMN_ALIASES:
            target = _COLUMN_ALIASES[alias]
            if target is not None:          # None means explicitly ignored
                headers_map[col] = target
    return headers_map


def _find_embedded_header_row(df: pd.DataFrame) -> int | None:
    """
    Detect broker-format files where the real column headers are buried inside
    a block of NaN rows.  Scans every row looking for one that satisfies at
    least ONE of the two layouts:

    Layout B  (IndiaInfoline / Groww):  Symbol + Average Price + Quantity Available
    Layout C  (Motilal / Sharekhan):    Stock Name + ISIN + Average buy price + Quantity

    Returns the (0-indexed) row index of the detected header row, or None.
    """
    # Keywords that indicate a stock *symbol / ticker* column header
    symbol_kw   = {"symbol", "stock code", "ticker", "scrip", "stock"}
    # Keywords that indicate a stock *name* column header (ISIN-only layouts)
    name_kw     = {"stock name", "company name", "company", "name"}
    # Price column keywords
    price_kw    = {"average price", "avg price", "buying price",
                   "buy price", "price", "average buy price"}
    # Quantity column keywords
    qty_kw      = {"quantity", "qty", "shares", "quantity available"}
    # ISIN column keyword (present in Layout C)
    isin_kw     = {"isin"}

    for idx, row in df.iterrows():
        cells = {str(v).strip().lower() for v in row.values if pd.notna(v)}
        has_price = bool(cells & price_kw)
        has_qty   = bool(cells & qty_kw)
        # Layout B: symbol + price + qty
        if cells & symbol_kw and has_price and has_qty:
            return int(idx)
        # Layout C: stock name + ISIN + price + qty  (no ticker column)
        if cells & name_kw and cells & isin_kw and has_price and has_qty:
            return int(idx)
    return None


def _resolve_isin_to_symbol(isin: str) -> str | None:
    """
    Resolve an ISIN code to its NSE (preferred) or BSE ticker symbol using
    yfinance's search API.  Returns the bare ticker (without .NS/.BO suffix),
    or None if the ISIN cannot be resolved.

    Examples:
        'INE084K01015'  →  'AMANTA'
        'INE571B01036'  →  'JAYBARMARU'
        'IN9148I01010'  →  None   (unlisted / not found on yfinance)
    """
    try:
        results = yf.Search(isin, max_results=5)
        quotes  = results.quotes
    except Exception:
        return None

    if not quotes:
        return None

    # Prefer NSE (.NS) over BSE (.BO)
    nse_hits = [q for q in quotes if q.get("symbol", "").endswith(".NS")]
    bse_hits = [q for q in quotes if q.get("symbol", "").endswith(".BO")]
    best = nse_hits[0] if nse_hits else (bse_hits[0] if bse_hits else quotes[0])

    raw_symbol = best.get("symbol", "")
    # Strip exchange suffix (.NS / .BO)
    return raw_symbol.replace(".NS", "").replace(".BO", "").strip() or None


def _parse_excel_to_dataframe(file_path: Path) -> pd.DataFrame:
    """
    Robustly parse an uploaded Excel file into a normalised DataFrame with
    columns: Company Name, Stock Code, Exchange, Buying Price, Quantity.

    Handles three real-world layouts:

    Layout A – simple / EquityPulse export
    ----------------------------------------
    Headers at row 0.  Column names map directly to standard aliases
    (e.g. 'Stock Code', 'Quantity', 'Buying Price').

    Layout B – broker holdings export (IndiaInfoline / Groww style)
    ---------------------------------------------------------------
    Multi-sheet workbook; 'Equity' sheet preferred.  Summary rows sit at the
    top with all 'Unnamed' columns.  Real header row is detected automatically.
    Columns include: Symbol | ISIN | Average Price | Quantity Available.

    Layout C – broker holdings export with ISIN only (Motilal / Sharekhan)
    -----------------------------------------------------------------------
    Single sheet.  Summary rows at top with 'Unnamed' columns.  Embedded
    header row has: Stock Name | ISIN | Quantity | Average buy price.
    No ticker/symbol column — symbols are resolved via yf.Search(ISIN).
    Rows whose ISIN cannot be resolved are skipped with a warning.
    """
    try:
        xl = pd.ExcelFile(file_path)
    except Exception as exc:
        raise ValueError(f"Could not open uploaded file: {exc}")

    sheet_names = xl.sheet_names

    # --- Sheet selection priority -------------------------------------------
    # Prefer a sheet literally named 'Equity'; fall back to the first sheet.
    preferred_order = ["Equity", "equity", "EQUITY"]
    target_sheet = next((s for s in preferred_order if s in sheet_names), sheet_names[0])

    # Read raw (no header assumption) so we can scan all rows
    raw = xl.parse(target_sheet, header=None)

    # -----------------------------------------------------------------------
    # Layout A: headers at row 0
    # -----------------------------------------------------------------------
    row0_headers  = [str(v).strip() for v in raw.iloc[0].values]
    headers_map_a = _map_columns(row0_headers)

    if all(f in headers_map_a.values() for f in _REQUIRED_FIELDS):
        # Standard read — pandas picks up row-0 as headers
        df = xl.parse(target_sheet)
        df = df.loc[:, ~df.columns.str.match(r'^Unnamed')]   # drop index cols
        headers_map = _map_columns(list(df.columns))
        df = df.rename(columns=headers_map)
        isin_col_present = "ISIN" in df.columns

    else:
        # -----------------------------------------------------------------------
        # Layout B / C: embedded header row somewhere below the summary block
        # -----------------------------------------------------------------------
        header_row_idx = _find_embedded_header_row(raw)
        if header_row_idx is None:
            raise ValueError(
                "Could not detect column headers in the uploaded file. "
                "Expected columns: Stock Code / Symbol / Stock Name, "
                "Buying Price / Average Price / Average buy price, "
                "Quantity / Quantity Available."
            )

        header_values = [str(v).strip() for v in raw.iloc[header_row_idx].values]
        data_rows     = raw.iloc[header_row_idx + 1:].copy()
        data_rows.columns = header_values

        headers_map = _map_columns(header_values)

        # For Layout C the 'Stock Code' column won't be in headers_map yet
        # (only Company Name + ISIN + Buying Price + Quantity are present).
        # We accept that and resolve symbols later.
        layout_c = (
            "Stock Code" not in headers_map.values()
            and "ISIN"   in headers_map.values()
            and "Buying Price" in headers_map.values()
            and "Quantity"     in headers_map.values()
        )

        if not layout_c and not all(f in headers_map.values() for f in _REQUIRED_FIELDS):
            raise ValueError(
                f"Uploaded file missing required columns.  "
                f"Detected headers: {header_values}.  "
                f"Need: Stock Code / Symbol / (Stock Name + ISIN), "
                f"Buying Price / Average Price, Quantity."
            )

        df = data_rows.rename(columns=headers_map)
        isin_col_present = "ISIN" in df.columns

    # --- Normalise optional columns ----------------------------------------
    if "Company Name" not in df.columns:
        df["Company Name"] = df.get("Stock Code", "")
    if "Exchange" not in df.columns:
        df["Exchange"] = "NSE"

    # -----------------------------------------------------------------------
    # Layout C: resolve ISIN → Stock Code when no symbol column exists
    # -----------------------------------------------------------------------
    if "Stock Code" not in df.columns and isin_col_present:
        resolved_codes: list[str | None] = []
        for _, row in df.iterrows():
            isin_val = str(row.get("ISIN", "")).strip()
            if not isin_val or isin_val.lower() == "nan":
                resolved_codes.append(None)
            else:
                resolved_codes.append(_resolve_isin_to_symbol(isin_val))
        df["Stock Code"] = resolved_codes

    # Keep only canonical columns
    keep_cols = ["Company Name", "Stock Code", "Exchange", "Buying Price", "Quantity"]
    if isin_col_present:
        keep_cols.insert(2, "ISIN")   # carry ISIN through for reference
    available = [c for c in keep_cols if c in df.columns]
    df = df[available].copy()

    # Drop rows with empty / NaN / unresolved Stock Code
    df = df.dropna(subset=["Stock Code"])
    df = df[df["Stock Code"].astype(str).str.strip() != ""]
    df = df[df["Stock Code"].astype(str).str.lower().str.strip() != "nan"]
    df = df[df["Stock Code"].astype(str).str.strip() != "-"]

    # Filter out rows whose price or quantity are invalid (summary/total rows)
    df["_price"] = df["Buying Price"].apply(_parse_price)
    df["_qty"]   = df["Quantity"].apply(_parse_qty)
    df = df[df["_price"].notna() & df["_qty"].notna() & (df["_price"] > 0) & (df["_qty"] > 0)]
    df = df.drop(columns=["_price", "_qty"])

    # Ensure Exchange column exists after potential ISIN-column insertion
    if "Exchange" not in df.columns:
        df["Exchange"] = "NSE"

    df = df.reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# validate_portfolio_file
# ---------------------------------------------------------------------------

def validate_portfolio_file(file_path: Path, username: str) -> dict:
    """
    Read an uploaded Excel file (any supported layout) and compare it
    row-by-row against the user's live portfolio in Cosmos DB.

    Supported file layouts
    ----------------------
    * Simple / EquityPulse export  — headers at row 0:
        Stock Code | Buying Price | Quantity  (plus optional Company Name, Exchange)

    * Broker holdings export (e.g. IndiaInfoline, Groww):
        Multi-sheet workbook; the 'Equity' sheet is preferred.
        Real column headers ('Symbol', 'Average Price', 'Quantity Available')
        may be buried below a summary block — detected automatically.

    Returns
    -------
    dict with:
      rows        — list of per-row comparison dicts
      not_in_file — stocks present in DB but absent from the uploaded file
      summary     — counts: total_in_file, match, mismatch, not_in_db, not_in_file
    """
    up_df = _parse_excel_to_dataframe(file_path)   # raises ValueError on failure

    # Fetch live DB portfolio and build an O(1) lookup by stock code
    db_df = read_stocks(username)
    db_lookup: dict[str, any] = {
        str(r["Stock Code"]).strip().upper(): r
        for _, r in db_df.iterrows()
    }


    rows: list[dict] = []
    seen_codes: set[str] = set()

    for _, row in up_df.iterrows():
        code = str(row["Stock Code"]).strip().upper()
        if not code or code.lower() == "nan":
            continue

        file_price = _parse_price(row["Buying Price"])
        file_qty   = _parse_qty(row["Quantity"])
        file_exch  = (
            str(row["Exchange"]).strip().upper()
            if pd.notna(row.get("Exchange"))
            else "NSE"
        )

        seen_codes.add(code)
        entry: dict = {
            "stock_code":    code,
            "company_name":  str(row.get("Company Name", code)).strip(),
            "isin":          str(row["ISIN"]).strip() if "ISIN" in up_df.columns and pd.notna(row.get("ISIN")) else None,
            "exchange_file": file_exch,
            "price_file":    file_price,
            "qty_file":      file_qty,
            "price_db":      None,
            "qty_db":        None,
            "exchange_db":   None,
            "status":        "not_in_db",
            "mismatches":    [],
        }

        if code in db_lookup:
            db_row   = db_lookup[code]
            db_price = float(db_row["Buying Price"])
            db_qty   = round(float(db_row["Quantity"]))
            db_exch  = str(db_row["Exchange"]).strip().upper()

            entry["price_db"]    = db_price
            entry["qty_db"]      = db_qty
            entry["exchange_db"] = db_exch

            mismatches: list[str] = []
            if file_qty is not None and file_qty != db_qty:
                mismatches.append("qty")

            if not mismatches:
                entry["status"] = "match"
            elif len(mismatches) == 1:
                entry["status"] = f"{mismatches[0]}_mismatch"
            else:
                entry["status"] = "multi_mismatch"
            entry["mismatches"] = mismatches

        rows.append(entry)

    # Stocks in DB but NOT in the uploaded file
    not_in_file: list[dict] = [
        {
            "stock_code":   code,
            "company_name": str(db_row.get("Company Name", code)).strip(),
            "exchange_db":  str(db_row["Exchange"]).strip().upper(),
            "price_db":     float(db_row["Buying Price"]),
            "qty_db":       float(db_row["Quantity"]),
        }
        for code, db_row in db_lookup.items()
        if code not in seen_codes
    ]

    match_count    = sum(1 for r in rows if r["status"] == "match")
    mismatch_count = sum(1 for r in rows if r["status"] not in {"match", "not_in_db"})
    not_in_db      = sum(1 for r in rows if r["status"] == "not_in_db")

    return {
        "rows":        rows,
        "not_in_file": not_in_file,
        "summary": {
            "total_in_file": len(rows),
            "match":         match_count,
            "mismatch":      mismatch_count,
            "not_in_db":     not_in_db,
            "not_in_file":   len(not_in_file),
        },
    }


def merge_uploaded_file(file_path: Path, username: str) -> dict:
    """
    Read uploaded Excel (any supported layout), validate, and merge stocks
    into the user's portfolio in Cosmos DB.

    Delegates all file parsing to _parse_excel_to_dataframe so that both
    simple files and broker holdings exports are handled identically.
    """
    _check_portfolio_writable()

    up_df = _parse_excel_to_dataframe(file_path)   # raises ValueError on failure

    merged_count   = 0
    added_count    = 0
    skipped_count  = 0
    skipped_details: list[str] = []

    for _, row in up_df.iterrows():
        c_code = str(row["Stock Code"]).strip().upper()
        if not c_code or c_code.lower() == "nan":
            continue

        try:
            c_name = str(row["Company Name"]).strip()
            c_exch = str(row["Exchange"]).strip().upper()
            price  = _parse_price(row["Buying Price"])
            qty    = _parse_qty(row["Quantity"])

            if price is None or qty is None or price <= 0 or qty <= 0:
                raise ValueError("Price and quantity must be positive numbers.")

            res = add_stock(c_name, c_code, c_exch, float(price), float(qty), username)
            if res["action"] == "merged":
                merged_count += 1
            else:
                added_count += 1
        except PermissionError:
            skipped_count += 1
            skipped_details.append(f"{c_code}: Could not save — portfolio is locked.")
        except Exception as err:
            skipped_count += 1
            skipped_details.append(f"{c_code}: {err}")

    return {
        "added":          added_count,
        "merged":         merged_count,
        "skipped":        skipped_count,
        "skipped_details": skipped_details,
    }


def send_portfolio_email(pdf_bytes: bytes) -> dict:
    """
    Send the portfolio PDF report using Azure Communication Services.
    Always uses the default recipient from the .env file.
    """
    connection_string = os.getenv("AZURE_COMMUNICATION_CONNECTION_STRING")
    sender_address = os.getenv("AZURE_EMAIL_SENDER")
    
    # Always fetch recipient from .env directly
    to_email = os.getenv("DEFAULT_REPORT_RECIPIENT")

    if not connection_string or "dummy" in connection_string:
        raise ValueError(
            "Azure Communication Services connection string is missing or is set to a dummy value. "
            "Please update the AZURE_COMMUNICATION_CONNECTION_STRING in your .env file."
        )
    if not sender_address or "dummy" in sender_address:
        raise ValueError(
            "Sender email address is missing or is set to a dummy value. "
            "Please update AZURE_EMAIL_SENDER in your .env file."
        )
    if not to_email or "example.com" in to_email or to_email == "string" or "@" not in to_email:
        raise ValueError(
            f"Recipient email address '{to_email}' is invalid or missing. "
            "Please check recipient input (replace 'string' with a valid email) or set DEFAULT_REPORT_RECIPIENT in your .env file."
        )

    try:
        # Initialize Email Client
        email_client = EmailClient.from_connection_string(connection_string)

        # Base64 encode attachment
        import base64
        attachment_content_b64 = base64.b64encode(pdf_bytes).decode("utf-8")

        # Create message dictionary
        message = {
            "senderAddress": sender_address,
            "recipients": {
                "to": [{"address": to_email}]
            },
            "content": {
                "subject": "Your EquityPulse Indian Stock Portfolio Report",
                "plainText": (
                    "Hello,\n\n"
                    "Please find attached your professional EquityPulse Stock Portfolio Report. "
                    "This report contains performance metrics, valuations, weights, and "
                    "20/50/100/200 simple moving averages (SMA) status indicators.\n\n"
                    "Best regards,\n"
                    "EquityPulse Analyzer Engine"
                )
            },
            "attachments": [
                {
                    "name": "EquityPulse_Portfolio_Report.pdf",
                    "contentType": "application/pdf",
                    "contentInBase64": attachment_content_b64
                }
            ]
        }

        # Send email asynchronously or synchronously (wait for completion)
        poller = email_client.begin_send(message)
        result = poller.result()
        return {"status": "success", "message_id": result.get("messageId", "Unknown")}

    except Exception as e:
        raise RuntimeError(f"Failed to send email via Azure: {e}")

def update_stock_details(symbol: str, new_company_name: str, new_stock_code: str, new_exchange: str, username: str, tag: str = None, row_color: str = None) -> dict:
    """Update only the metadata of a stock in Cosmos DB for a user."""
    from app.cosmos_service import cosmos_service
    formatted_symbol = format_symbol(symbol).upper()
    exchange = "NSE" if formatted_symbol.endswith(".NS") else "BSE" if formatted_symbol.endswith(".BO") else "NSE"
    
    existing = cosmos_service.get_stock(formatted_symbol, exchange, username)
    if not existing:
        raise KeyError(f"Stock '{formatted_symbol}' not found in portfolio.")
        
    if new_company_name:
        existing["Company Name"] = new_company_name.strip()
        
    if tag is not None:
        existing["Tag"] = tag.strip()

    # Persist row highlight color (None clears it)
    if row_color is not None and row_color.strip():
        existing["Row Color"] = row_color.strip()
    else:
        existing["Row Color"] = None
        
    if new_stock_code or new_exchange:
        old_exchange = existing["Exchange"]
        old_id = existing["id"]
        
        if new_stock_code:
            existing["Stock Code"] = new_stock_code.strip().upper()
        if new_exchange:
            existing["Exchange"] = new_exchange.strip().upper()
            
        new_suffix = ".NS" if existing["Exchange"] == "NSE" else ".BO" if existing["Exchange"] == "BSE" else ""
        new_id = f"{username}_{existing['Stock Code']}{new_suffix}"
        existing["id"] = new_id
        
        cosmos_service.delete_stock(old_id, old_exchange, username)
        cosmos_service.upsert_stock(existing, username)
    else:
        cosmos_service.upsert_stock(existing, username)
    
    return {"status": "success", "message": f"Stock {formatted_symbol} details updated successfully."}

