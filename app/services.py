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
COLUMNS = ["Stock Name", "Buying Price", "Quantity"]

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
    """Read stocks from the Excel file."""
    ensure_excel_file()
    try:
        df = pd.read_excel(EXCEL_PATH)
        # Ensure correct columns exist
        for col in COLUMNS:
            if col not in df.columns:
                df[col] = None
        # Clean data (ensure stock names are uppercase strings, drop rows where all columns are empty)
        df = df.dropna(subset=["Stock Name"])
        df["Stock Name"] = df["Stock Name"].astype(str).str.strip().str.upper()
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
    df["Stock Name"] = df["Stock Name"].astype(str).str.strip().str.upper()
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
        symbol = str(row["Stock Name"]).upper()
        buying_price = float(row["Buying Price"])
        quantity = float(row["Quantity"])
        
        try:
            current_price, sma20, sma50, sma100, sma200, actual_symbol, today_change, today_change_pct, company_name = get_stock_data(symbol)
            investment_value = buying_price * quantity
            current_value = current_price * quantity
            gain_loss = current_value - investment_value
            gain_loss_pct = ((current_price - buying_price) / buying_price * 100) if buying_price > 0 else 0.0
            today_return_val = today_change * quantity
            
            def clean_nan(val):
                return None if (isinstance(val, float) and math.isnan(val)) else val

            results.append({
                "company_name": company_name,
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
                "company_name": symbol,
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

def add_stock(symbol: str, price: float, quantity: float) -> dict:
    """
    Add a stock transaction.
    If stock already exists, merge it:
    - New quantity = old_qty + new_qty
    - New average price = (old_price * old_qty + new_price * new_qty) / (old_qty + new_qty)
    NOTE: Ticker validation via yfinance is intentionally skipped here to keep the
    operation fast. Live data is fetched lazily when the portfolio is displayed.
    """
    formatted_symbol = format_symbol(symbol)
    df = read_stocks()
    symbol_upper = formatted_symbol.upper()
    
    # Check if stock exists by base symbol match
    def get_base(s):
        s = s.strip().upper()
        if s.endswith(".NS") or s.endswith(".BO"):
            s = s.rsplit(".", 1)[0]
        s = _NSE_SEGMENT_MARKERS.sub("", s)
        return s
        
    req_base = get_base(symbol_upper)
    
    match_idx = None
    for idx, row in df.iterrows():
        row_base = get_base(str(row["Stock Name"]))
        if row_base == req_base:
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
        action = "merged"
        symbol_upper = df.loc[match_idx, "Stock Name"]
    else:
        new_row = pd.DataFrame([{"Stock Name": symbol_upper, "Buying Price": price, "Quantity": quantity}])
        df = pd.concat([df, new_row], ignore_index=True)
        action = "added"
        
    write_stocks(df)
    return {"symbol": symbol_upper, "action": action}

def update_stock(symbol: str, price: float, quantity: float, new_symbol: str = None) -> dict:
    """Directly update price and quantity of a stock (and optionally its symbol)."""
    # First, validate symbol format
    formatted_symbol = format_symbol(symbol)
    df = read_stocks()
    symbol_upper = formatted_symbol.upper()
    
    def get_base(s):
        s = s.strip().upper()
        if s.endswith(".NS") or s.endswith(".BO"):
            s = s.rsplit(".", 1)[0]
        s = _NSE_SEGMENT_MARKERS.sub("", s)
        return s
        
    req_base = get_base(symbol_upper)
    
    match_idx = None
    for idx, row in df.iterrows():
        row_base = get_base(str(row["Stock Name"]))
        if row_base == req_base:
            match_idx = idx
            break
            
    if match_idx is None:
        raise KeyError(f"Stock '{symbol_upper}' not found in portfolio.")
        
    df.loc[match_idx, "Buying Price"] = price
    df.loc[match_idx, "Quantity"] = quantity
    
    if new_symbol:
        formatted_new_symbol = format_symbol(new_symbol)
        df.loc[match_idx, "Stock Name"] = formatted_new_symbol.upper()
    
    write_stocks(df)
    return {"symbol": df.loc[match_idx, "Stock Name"], "action": "updated"}

def delete_stock(symbol: str) -> dict:
    """Delete a stock from the portfolio."""
    symbol_upper = symbol.strip().upper()
    df = read_stocks()
    
    def get_base(s):
        s = s.strip().upper()
        if s.endswith(".NS") or s.endswith(".BO"):
            s = s.rsplit(".", 1)[0]
        s = _NSE_SEGMENT_MARKERS.sub("", s)
        return s
        
    req_base = get_base(symbol_upper)
    
    match_mask = df["Stock Name"].apply(lambda x: get_base(str(x)) == req_base)
            
    if not match_mask.any():
        raise KeyError(f"Stock '{symbol_upper}' not found in portfolio.")
        
    actual_deleted = df[match_mask]["Stock Name"].iloc[0]
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
    Expected columns: Stock Name, Buying Price, Quantity.
    Handles extra/unnamed index columns and fuzzy column name matching.
    """
    # Fail fast with a helpful message if the portfolio file is currently locked
    _check_portfolio_writable()

    try:
        up_df = pd.read_excel(file_path)
    except Exception as e:
        raise ValueError(f"Could not parse uploaded file: {e}")

    # Drop fully unnamed/index columns (e.g. 'Unnamed: 0') that pandas adds when
    # the Excel file was saved with the DataFrame index included.
    up_df = up_df.loc[:, ~up_df.columns.str.match(r'^Unnamed')]

    # Step 1: Try exact (case-insensitive) header matches first
    exact_map = {
        "stock name": "Stock Name",
        "ticker": "Stock Name",
        "symbol": "Stock Name",
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

    # Step 2: For any required field still missing, fall back to keyword fuzzy search
    resolved = set(headers_map.values())
    for col in up_df.columns:
        if col in headers_map:
            continue  # already mapped
        col_clean = str(col).strip().lower()
        if "Stock Name" not in resolved:
            if "stock" in col_clean or "ticker" in col_clean:
                headers_map[col] = "Stock Name"
                resolved.add("Stock Name")
        if "Buying Price" not in resolved:
            if "price" in col_clean or "buy" in col_clean:
                headers_map[col] = "Buying Price"
                resolved.add("Buying Price")
        if "Quantity" not in resolved:
            if "qty" in col_clean or "quantity" in col_clean or "share" in col_clean:
                headers_map[col] = "Quantity"
                resolved.add("Quantity")

    # Validate all required fields were resolved
    required_fields = ["Stock Name", "Buying Price", "Quantity"]
    for f in required_fields:
        if f not in headers_map.values():
            raise ValueError(
                f"Uploaded file missing required column: '{f}'. "
                f"Columns found: {list(up_df.columns)}. "
                f"Expected columns: 'Stock Name', 'Buying Price', 'Quantity'."
            )

    # Rename and filter to only required columns
    up_df = up_df.rename(columns=headers_map)
    up_df = up_df[required_fields].dropna(subset=["Stock Name"])
    # Drop rows where Stock Name is empty or whitespace
    up_df = up_df[up_df["Stock Name"].astype(str).str.strip() != ""]

    # Merge rows into portfolio
    merged_count = 0
    added_count = 0
    skipped_count = 0
    skipped_details = []

    for _, row in up_df.iterrows():
        raw_symbol = str(row["Stock Name"]).strip()
        if not raw_symbol or raw_symbol.lower() == "nan":
            continue

        try:
            fmt_sym = format_symbol(raw_symbol)
            price = float(row["Buying Price"])
            qty = float(row["Quantity"])

            if price <= 0 or qty <= 0:
                raise ValueError("Price and quantity must be positive numbers.")

            res = add_stock(fmt_sym, price, qty)
            if res["action"] == "merged":
                merged_count += 1
            else:
                added_count += 1
        except PermissionError:
            # Provide a clear, actionable message when stocks.xlsx is locked
            skipped_count += 1
            skipped_details.append(
                f"{raw_symbol}: Could not save — 'stocks.xlsx' is locked. "
                f"Please close the file in Excel and try uploading again."
            )
        except Exception as err:
            skipped_count += 1
            skipped_details.append(f"{raw_symbol}: {err}")

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

