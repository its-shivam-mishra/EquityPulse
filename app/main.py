import shutil
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException, UploadFile, File, BackgroundTasks, Body, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
import jwt
from datetime import datetime, timedelta

from app.services import (
    ensure_excel_file,
    get_all_stocks_with_metrics,
    get_stock_history,
    add_stock,
    update_stock,
    delete_stock,
    merge_uploaded_file,
    send_portfolio_email,
    update_stock_details
)
from app.pdf_generator import generate_portfolio_pdf

# Initialize application

app = FastAPI(
    title="Stock Portfolio Analyser",
    description="FastAPI + yfinance  backend for tracking Indian Stock Portfolio.",
    version="1.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Auth setup
SECRET_KEY = "equitypulse_secret"
ALGORITHM = "HS256"
security = HTTPBearer()

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=7)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return username
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

class UserAuth(BaseModel):
    username: str
    password: str

@app.post("/api/auth/register")
def register(user: UserAuth):
    from app.cosmos_service import cosmos_service
    existing = cosmos_service.get_user(user.username)
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")
    cosmos_service.create_user(user.username, user.password)
    token = create_access_token(data={"sub": user.username})
    return {"access_token": token, "token_type": "bearer", "username": user.username}

@app.post("/api/auth/login")
def login(user: UserAuth):
    from app.cosmos_service import cosmos_service
    db_user = cosmos_service.get_user(user.username)
    if not db_user or db_user.get("password") != user.password:
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    token = create_access_token(data={"sub": user.username})
    return {"access_token": token, "token_type": "bearer", "username": user.username}

# Pydantic Schemas for Requests
class StockTransaction(BaseModel):
    company_name: str = Field(..., description="Human readable company name")
    stock_code: str = Field(..., description="Base ticker symbol (e.g. RELIANCE, TCS)")
    exchange: str = Field(..., description="Exchange abbreviation (e.g. NSE, BSE)")
    price: float = Field(..., gt=0, description="Purchase price per share")
    quantity: float = Field(..., gt=0, description="Quantity of shares purchased")
    tag: Optional[str] = Field(None, description="Optional tag (e.g. Tech, Core)")

class StockDetailsUpdateData(BaseModel):
    company_name: str = Field(..., description="New company name")
    stock_code: str = Field(..., description="New base ticker symbol")
    exchange: str = Field(..., description="New exchange")
    tag: Optional[str] = Field(None, description="New tag")

class StockUpdateData(BaseModel):
    company_name: str = Field(..., description="New company name")
    stock_code: str = Field(..., description="New base ticker symbol")
    exchange: str = Field(..., description="New exchange")
    price: float = Field(..., gt=0, description="New average buying price per share")
    quantity: float = Field(..., gt=0, description="New quantity of shares")
    tag: Optional[str] = Field(None, description="New tag")

class DailySnapshotData(BaseModel):
    total_invested: float = Field(..., description="Total invested amount")
    current_value: float = Field(..., description="Current portfolio value")
    nifty_smallcap_100: float = Field(..., description="Current Nifty SmallCap 100 value")

# API Endpoints
@app.get("/api/stocks")
def get_stocks(username: str = Depends(get_current_user)):
    """Retrieve all stocks from portfolio with current prices and SMAs."""
    try:
        return get_all_stocks_with_metrics(username)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch stock list: {e}")

@app.post("/api/stocks")
def create_stock_transaction(transaction: StockTransaction, username: str = Depends(get_current_user)):
    """
    Add a new stock transaction.
    If the stock already exists, it merges the transaction:
    increases quantity and calculates weighted average buying price.
    """
    try:
        result = add_stock(
            company_name=transaction.company_name,
            stock_code=transaction.stock_code,
            exchange=transaction.exchange,
            price=transaction.price,
            quantity=transaction.quantity,
            username=username,
            tag=transaction.tag
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")

@app.post("/api/stocks/upload")
def upload_excel(file: UploadFile = File(...), username: str = Depends(get_current_user)):
    """Upload an Excel file to merge new stocks into the portfolio."""
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Only Excel files (.xlsx, .xls) are allowed.")
        
    temp_dir = Path("temp")
    temp_dir.mkdir(exist_ok=True)
    temp_file_path = temp_dir / file.filename
    
    try:
        # Save uploaded file to temp location
        with temp_file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # Parse and merge
        result = merge_uploaded_file(temp_file_path, username)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process file: {e}")
    finally:
        # Clean up temp file
        if temp_file_path.exists():
            temp_file_path.unlink()

@app.get("/api/stocks/{symbol}/history")
def get_history(symbol: str, period: str = "1y", username: str = Depends(get_current_user)):
    """Fetch historical prices and SMA markers for plotting a stock chart."""
    valid_periods = ["1mo", "3mo", "6mo", "1y", "2y", "5y"]
    if period not in valid_periods:
        raise HTTPException(status_code=400, detail=f"Invalid period. Choose from {valid_periods}")
    try:
        return get_stock_history(symbol, period)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch history: {e}")

@app.put("/api/stocks/{symbol}")
def update_stock_transaction(symbol: str, data: StockUpdateData, username: str = Depends(get_current_user)):
    """Directly update price, quantity, and metadata of a stock in the Excel sheet."""
    try:
        result = update_stock(symbol, data.price, data.quantity, data.company_name, data.stock_code, data.exchange, username, data.tag)
        return result
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")

@app.put("/api/stocks/{symbol}/details")
def update_stock_details_endpoint(symbol: str, data: StockDetailsUpdateData, username: str = Depends(get_current_user)):
    """Update only the details (name, code, exchange) of a stock."""
    try:
        result = update_stock_details(symbol, data.company_name, data.stock_code, data.exchange, username, data.tag)
        return result
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")

@app.delete("/api/stocks/{symbol}")
def remove_stock(symbol: str, username: str = Depends(get_current_user)):
    """Remove a stock from the portfolio."""
    try:
        result = delete_stock(symbol, username)
        return result
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


@app.post("/api/report/email")
def email_portfolio_report(background_tasks: BackgroundTasks = None, username: str = Depends(get_current_user)):
    """
    Generate the portfolio PDF report and send it to the default recipient from .env.
    """
    try:
        
        # 1. Fetch current stock data
        stocks_data = get_all_stocks_with_metrics(username)
        if not stocks_data:
            raise HTTPException(status_code=400, detail="Portfolio is empty. Please add stocks before generating a report.")
            
        # 2. Generate PDF bytes
        pdf_bytes = generate_portfolio_pdf(stocks_data)
        
        # 3. Send email using helper
        result = send_portfolio_email(pdf_bytes)
        return result
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate and email report: {e}")


@app.get("/api/market-index/{symbol}")
def get_market_index(symbol: str, username: str = Depends(get_current_user)):
    """Fetch current price and change for a market index."""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        
        try:
            fast_info = ticker.fast_info
            current_price = float(fast_info.last_price)
            prev_close = float(fast_info.previous_close)
        except Exception:
            raise HTTPException(status_code=404, detail="Index data not found")
        
        if prev_close and prev_close > 0:
            change = current_price - prev_close
            change_pct = (change / prev_close) * 100
        else:
            change = 0.0
            change_pct = 0.0
            
        return {
            "symbol": symbol,
            "current_value": current_price,
            "change": change,
            "change_pct": change_pct
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/stats/snapshot")
def save_daily_snapshot(data: DailySnapshotData, username: str = Depends(get_current_user)):
    """Save daily snapshot of portfolio stats. Overwrites existing max current_value."""
    from app.cosmos_service import cosmos_service
    from datetime import date
    try:
        today_str = date.today().isoformat()
        result = cosmos_service.upsert_daily_stat(
            username=username, 
            date=today_str, 
            invested=data.total_invested, 
            current_val=data.current_value, 
            smallcap=data.nifty_smallcap_100
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save snapshot: {e}")

@app.get("/api/stats/history")
def get_stats_history(username: str = Depends(get_current_user)):
    """Get all historical snapshots for user."""
    from app.cosmos_service import cosmos_service
    try:
        items = cosmos_service.get_historical_stats(username)
        return items
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch stats history: {e}")

# Mount Static Files to serve frontend SPA at root "/"
# Check if static directory exists first
static_dir = Path("app/static")
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/", StaticFiles(directory="app/static", html=True), name="static")

