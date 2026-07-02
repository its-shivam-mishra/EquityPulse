import os
import re as _re
import math
import shutil
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
COLUMNS = ["Company Name", "Stock Code", "Exchange", "Buying Price", "Quantity"]

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

def read_stocks() -> pd.DataFrame:
    """Read stocks from the Excel file and auto-migrate legacy format."""
    ensure_excel_file()
    try:
        df = pd.read_excel(EXCEL_PATH)
        
        # Legacy migration check: if 'Stock Name' exists but 'Company Name' does not
        if "Stock Name" in df.columns and "Company Name" not in df.columns:
            # We are reading an old file. Let's migrate it in memory and then overwrite.
            df["Company Name"] = df["Stock Name"]
            df["Stock Code"] = ""
            df["Exchange"] = ""
            for i, row in df.iterrows():
                symbol = str(row["Stock Name"]).strip().upper()
                if symbol.endswith(".NS"):
                    df.at[i, "Stock Code"] = symbol[:-3]
                    df.at[i, "Exchange"] = "NSE"
                elif symbol.endswith(".BO"):
                    df.at[i, "Stock Code"] = symbol[:-3]
                    df.at[i, "Exchange"] = "BSE"
                else:
                    df.at[i, "Stock Code"] = symbol
                    df.at[i, "Exchange"] = "NSE" # Default
            
            # Fetch human-readable company names for the legacy entries
            # We use a dummy object since we don't have ticker_obj here
            for i, row in df.iterrows():
                sym = f"{df.at[i, 'Stock Code']}.{'NS' if df.at[i, 'Exchange'] == 'NSE' else 'BO'}"
                ticker = yf.Ticker(sym)
                df.at[i, "Company Name"] = get_company_name(ticker, sym)

            # Drop old column and save immediately
            df = df.drop(columns=["Stock Name"])
            write_stocks(df) # Will re-read from memory here? Wait, write_stocks takes df. Let's just pass it.

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
        return df[COLUMNS]
    except Exception as e:
        print(f"Error reading Excel file: {e}")
        return pd.DataFrame(columns=COLUMNS)

def write_stocks(df: pd.DataFrame):
    """Write DataFrame of stocks back to Excel.

    Uses an atomic write strategy: writes to a temporary file in the same
    directory first, then replaces the target. This avoids PermissionError
    when stocks.xlsx is concurrently open in Excel (which locks the file on
    Windows but still allows replacement via a temp-file swap).
    """
    ensure_excel_file()
    # Format
    df["Company Name"] = df["Company Name"].astype(str).str.strip()
    df["Stock Code"] = df["Stock Code"].astype(str).str.strip().str.upper()
    df["Exchange"] = df["Exchange"].astype(str).str.strip().str.upper()
    df["Buying Price"] = pd.to_numeric(df["Buying Price"], errors="coerce").fillna(0.0)
    df["Quantity"] = pd.to_numeric(df["Quantity"], errors="coerce").fillna(0.0)

    # Write to a sibling temp file, then atomically replace the target.
    # On Windows, shutil.move handles cross-device moves and uses
    # os.replace internally when source and destination are on the same volume.
    tmp_fd, tmp_path_str = tempfile.mkstemp(
        suffix=".xlsx", prefix="stocks_tmp_", dir=ASSETS_DIR
    )
    tmp_path = Path(tmp_path_str)
    try:
        os.close(tmp_fd)  # pandas opens the file itself
        df[COLUMNS].to_excel(tmp_path, index=False)
        shutil.move(str(tmp_path), str(EXCEL_PATH))
    except Exception:
        # Clean up orphaned temp file on failure
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise

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

def get_stock_data(symbol: str):
    """
    Fetch stock metadata: current price and SMA 20, 50, 100, 200.
    Returns: (current_price, sma20, sma50, sma100, sma200, actual_symbol)
    """
    formatted_symbol = format_symbol(symbol)
    ticker = yf.Ticker(formatted_symbol)
    
    # We query historical data for past 1 year (approx 250 trading days)
    # to calculate moving averages.
    hist = ticker.history(period="1y")
    
    # Automatic exchange fallback (NSE <-> BSE) if no historical data found
    if hist.empty:
        fallback_symbol = None
        if formatted_symbol.endswith(".NS"):
            fallback_symbol = formatted_symbol[:-3] + ".BO"
        elif formatted_symbol.endswith(".BO"):
            fallback_symbol = formatted_symbol[:-3] + ".NS"
            
        if fallback_symbol:
            fallback_ticker = yf.Ticker(fallback_symbol)
            fallback_hist = fallback_ticker.history(period="1y")
            if not fallback_hist.empty:
                formatted_symbol = fallback_symbol
                ticker = fallback_ticker
                hist = fallback_hist

    if hist.empty:
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
    hist = ticker.history(period=period)
    
    # Automatic exchange fallback (NSE <-> BSE) if no historical data found
    if hist.empty:
        fallback_symbol = None
        if formatted_symbol.endswith(".NS"):
            fallback_symbol = formatted_symbol[:-3] + ".BO"
        elif formatted_symbol.endswith(".BO"):
            fallback_symbol = formatted_symbol[:-3] + ".NS"
            
        if fallback_symbol:
            fallback_ticker = yf.Ticker(fallback_symbol)
            fallback_hist = fallback_ticker.history(period=period)
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
        "symbol": formatted_symbol
    }

def get_all_stocks_with_metrics() -> list:
    """Read stocks from Excel and enrich with real-time yfinance metrics."""
    df = read_stocks()
    results = []
    
    for _, row in df.iterrows():
        company_name_db = str(row["Company Name"]).strip()
        stock_code = str(row["Stock Code"]).strip().upper()
        exchange = str(row["Exchange"]).strip().upper()
        buying_price = float(row["Buying Price"])
        quantity = float(row["Quantity"])
        
        # Build symbol for yfinance
        suffix = ".NS" if exchange == "NSE" else ".BO" if exchange == "BSE" else ""
        symbol = f"{stock_code}{suffix}"
        
        try:
            current_price, sma20, sma50, sma100, sma200, actual_symbol, today_change, today_change_pct, fetched_company_name = get_stock_data(symbol)
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
                "symbol": actual_symbol,
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
                "status": "error",
                "error": str(e)
            })
            
    return results

def add_stock(company_name: str, stock_code: str, exchange: str, price: float, quantity: float) -> dict:
    """
    Add a stock transaction.
    If stock already exists, merge it:
    - New quantity = old_qty + new_qty
    - New average price = (old_price * old_qty + new_price * new_qty) / (old_qty + new_qty)
    """
    df = read_stocks()
    stock_code_upper = stock_code.strip().upper()
    exchange_upper = exchange.strip().upper()
    
    match_idx = None
    for idx, row in df.iterrows():
        if str(row["Stock Code"]).upper() == stock_code_upper and str(row["Exchange"]).upper() == exchange_upper:
            match_idx = idx
            break
    
    if match_idx is not None:
        old_price = float(df.loc[match_idx, "Buying Price"])
        old_qty = float(df.loc[match_idx, "Quantity"])
        
        total_qty = old_qty + quantity
        if total_qty > 0:
            avg_price = (old_price * old_qty + price * quantity) / total_qty
        else:
            avg_price = 0.0
            
        df.loc[match_idx, "Buying Price"] = avg_price
        df.loc[match_idx, "Quantity"] = total_qty
        # Optionally update company name to the newest provided
        df.loc[match_idx, "Company Name"] = company_name.strip()
        action = "merged"
    else:
        new_row = pd.DataFrame([{
            "Company Name": company_name.strip(),
            "Stock Code": stock_code_upper,
            "Exchange": exchange_upper,
            "Buying Price": price,
            "Quantity": quantity
        }])
        df = pd.concat([df, new_row], ignore_index=True)
        action = "added"
        
    write_stocks(df)
    return {"stock_code": stock_code_upper, "action": action}

def update_stock(symbol: str, price: float, quantity: float, new_company_name: str = None, new_stock_code: str = None, new_exchange: str = None) -> dict:
    """Directly update price, quantity, and optionally company name, stock code, and exchange."""
    # Find the stock by its current symbol (Stock Code + Exchange mapped)
    # Actually, the frontend will pass the symbol as "CODE.EXCHANGE". Let's parse it to find the row.
    formatted_symbol = format_symbol(symbol).upper()
    df = read_stocks()
    
    match_idx = None
    for idx, row in df.iterrows():
        stock_code = str(row["Stock Code"]).strip().upper()
        exchange = str(row["Exchange"]).strip().upper()
        suffix = ".NS" if exchange == "NSE" else ".BO" if exchange == "BSE" else ""
        row_symbol = f"{stock_code}{suffix}"
        
        if format_symbol(row_symbol).upper() == formatted_symbol:
            match_idx = idx
            break
            
    if match_idx is None:
        raise KeyError(f"Stock '{formatted_symbol}' not found in portfolio.")
        
    df.loc[match_idx, "Buying Price"] = price
    df.loc[match_idx, "Quantity"] = quantity
    
    if new_company_name:
        df.loc[match_idx, "Company Name"] = new_company_name.strip()
    if new_stock_code:
        df.loc[match_idx, "Stock Code"] = new_stock_code.strip().upper()
    if new_exchange:
        df.loc[match_idx, "Exchange"] = new_exchange.strip().upper()
    
    write_stocks(df)
    return {"stock_code": df.loc[match_idx, "Stock Code"], "action": "updated"}

def delete_stock(symbol: str) -> dict:
    """Delete a stock from the portfolio."""
    formatted_symbol = format_symbol(symbol).upper()
    df = read_stocks()
    
    match_mask = pd.Series([False] * len(df))
    actual_deleted = ""
    for idx, row in df.iterrows():
        stock_code = str(row["Stock Code"]).strip().upper()
        exchange = str(row["Exchange"]).strip().upper()
        suffix = ".NS" if exchange == "NSE" else ".BO" if exchange == "BSE" else ""
        row_symbol = f"{stock_code}{suffix}"
        
        if format_symbol(row_symbol).upper() == formatted_symbol:
            match_mask[idx] = True
            actual_deleted = row_symbol
            break
            
    if not match_mask.any():
        raise KeyError(f"Stock '{formatted_symbol}' not found in portfolio.")
        
    df = df[~match_mask]
    write_stocks(df)
    return {"symbol": actual_deleted, "action": "deleted"}

def _check_portfolio_writable():
    """Raise a descriptive ValueError if the portfolio Excel file is write-locked."""
    ensure_excel_file()
    try:
        # Try to open the file for writing; if it's locked by Excel this raises
        # PermissionError on Windows before we ever try to write.
        with open(EXCEL_PATH, "r+b"):
            pass
    except PermissionError:
        raise ValueError(
            "Cannot write to 'stocks.xlsx' — the file is currently open in Microsoft Excel "
            "or another program. Please close it and try the upload again."
        )


def merge_uploaded_file(file_path: Path) -> dict:
    """
    Read uploaded Excel, validate headers, and merge stocks into the main portfolio.
    Expected columns: Company Name, Stock Code, Exchange, Buying Price, Quantity.
    Handles extra/unnamed index columns and fuzzy column name matching.
    """
    # Fail fast with a helpful message if the portfolio file is currently locked
    _check_portfolio_writable()

    try:
        up_df = pd.read_excel(file_path)
    except Exception as e:
        raise ValueError(f"Could not parse uploaded file: {e}")

    # Drop fully unnamed/index columns
    up_df = up_df.loc[:, ~up_df.columns.str.match(r'^Unnamed')]

    # Step 1: Try exact (case-insensitive) header matches first
    exact_map = {
        "company name": "Company Name",
        "company": "Company Name",
        "stock code": "Stock Code",
        "stock": "Stock Code",
        "ticker": "Stock Code",
        "symbol": "Stock Code",
        "code": "Stock Code",
        "exchange": "Exchange",
        "market": "Exchange",
        "buying price": "Buying Price",
        "buy price": "Buying Price",
        "price": "Buying Price",
        "avg price": "Buying Price",
        "average price": "Buying Price",
        "quantity": "Quantity",
        "qty": "Quantity",
        "shares": "Quantity",
    }

    headers_map = {}
    for col in up_df.columns:
        col_clean = str(col).strip().lower()
        if col_clean in exact_map:
            headers_map[col] = exact_map[col_clean]

    # Validate required fields
    required_fields = ["Stock Code", "Buying Price", "Quantity"]
    for f in required_fields:
        if f not in headers_map.values():
            # Attempt fuzzy match as fallback
            for col in up_df.columns:
                if col in headers_map:
                    continue
                col_clean = str(col).strip().lower()
                if f == "Stock Code" and ("stock" in col_clean or "ticker" in col_clean or "name" in col_clean):
                    headers_map[col] = "Stock Code"
                    break
                if f == "Buying Price" and ("price" in col_clean or "buy" in col_clean):
                    headers_map[col] = "Buying Price"
                    break
                if f == "Quantity" and ("qty" in col_clean or "quantity" in col_clean or "share" in col_clean):
                    headers_map[col] = "Quantity"
                    break
                    
    for f in required_fields:
        if f not in headers_map.values():
            raise ValueError(
                f"Uploaded file missing required column: '{f}'. "
                f"Columns found: {list(up_df.columns)}. "
            )

    # Rename and filter
    up_df = up_df.rename(columns=headers_map)
    
    # Add optional columns if missing
    if "Company Name" not in up_df.columns:
        up_df["Company Name"] = up_df["Stock Code"]
    if "Exchange" not in up_df.columns:
        up_df["Exchange"] = "NSE"
        
    required_cols = ["Company Name", "Stock Code", "Exchange", "Buying Price", "Quantity"]
    up_df = up_df[required_cols].dropna(subset=["Stock Code"])
    up_df = up_df[up_df["Stock Code"].astype(str).str.strip() != ""]

    # Merge rows into portfolio
    merged_count = 0
    added_count = 0
    skipped_count = 0
    skipped_details = []

    for _, row in up_df.iterrows():
        c_code = str(row["Stock Code"]).strip().upper()
        if not c_code or c_code.lower() == "nan":
            continue

        try:
            c_name = str(row["Company Name"]).strip()
            c_exch = str(row["Exchange"]).strip().upper()
            price = float(row["Buying Price"])
            qty = float(row["Quantity"])

            if price <= 0 or qty <= 0:
                raise ValueError("Price and quantity must be positive numbers.")

            res = add_stock(c_name, c_code, c_exch, price, qty)
            if res["action"] == "merged":
                merged_count += 1
            else:
                added_count += 1
        except PermissionError:
            skipped_count += 1
            skipped_details.append(
                f"{c_code}: Could not save — 'stocks.xlsx' is locked. "
            )
        except Exception as err:
            skipped_count += 1
            skipped_details.append(f"{c_code}: {err}")

    return {
        "added": added_count,
        "merged": merged_count,
        "skipped": skipped_count,
        "skipped_details": skipped_details
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

def update_stock_details(symbol: str, new_company_name: str, new_stock_code: str, new_exchange: str) -> dict:
    """Update only the metadata of a stock."""
    formatted_symbol = format_symbol(symbol).upper()
    df = read_stocks()
    
    match_idx = None
    for idx, row in df.iterrows():
        stock_code = str(row["Stock Code"]).strip().upper()
        exchange = str(row["Exchange"]).strip().upper()
        suffix = ".NS" if exchange == "NSE" else ".BO" if exchange == "BSE" else ""
        row_symbol = f"{stock_code}{suffix}"
        
        if format_symbol(row_symbol).upper() == formatted_symbol:
            match_idx = idx
            break
            
    if match_idx is None:
        raise KeyError(f"Stock '{formatted_symbol}' not found in portfolio.")
        
    if new_company_name:
        df.loc[match_idx, "Company Name"] = new_company_name.strip()
    if new_stock_code:
        df.loc[match_idx, "Stock Code"] = new_stock_code.strip().upper()
    if new_exchange:
        df.loc[match_idx, "Exchange"] = new_exchange.strip().upper()
    
    write_stocks(df)
    return {"status": "success", "message": f"Stock {formatted_symbol} details updated successfully."}

