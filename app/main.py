import shutil
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException, UploadFile, File, BackgroundTasks, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.services import (
    ensure_excel_file,
    get_all_stocks_with_metrics,
    get_stock_history,
    add_stock,
    update_stock,
    delete_stock,
    merge_uploaded_file,
    send_portfolio_email
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

# Ensure Excel file exists on startup
@app.on_event("startup")
def startup_event():
    ensure_excel_file()

# Pydantic Schemas for Requests
class StockTransaction(BaseModel):
    symbol: str = Field(..., description="Stock symbol (e.g. RELIANCE, TCS.NS)")
    price: float = Field(..., gt=0, description="Purchase price per share")
    quantity: float = Field(..., gt=0, description="Quantity of shares purchased")

class StockUpdateData(BaseModel):
    price: float = Field(..., gt=0, description="New average buying price per share")
    quantity: float = Field(..., gt=0, description="New quantity of shares")
    new_symbol: Optional[str] = Field(None, description="Optional new symbol to rename to")

# API Endpoints
@app.get("/api/stocks")
def get_stocks():
    """Retrieve all stocks from portfolio with current prices and SMAs."""
    try:
        return get_all_stocks_with_metrics()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch stock list: {e}")

@app.post("/api/stocks")
def create_stock_transaction(transaction: StockTransaction):
    """
    Add a new stock transaction.
    If the stock already exists, it merges the transaction:
    increases quantity and calculates weighted average buying price.
    """
    try:
        result = add_stock(transaction.symbol, transaction.price, transaction.quantity)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")

@app.post("/api/stocks/upload")
def upload_excel(file: UploadFile = File(...)):
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
        result = merge_uploaded_file(temp_file_path)
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
def get_history(symbol: str, period: str = "1y"):
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
def update_stock_transaction(symbol: str, data: StockUpdateData):
    """Directly update price and quantity of a stock in the Excel sheet."""
    try:
        result = update_stock(symbol, data.price, data.quantity, data.new_symbol)
        return result
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")

@app.delete("/api/stocks/{symbol}")
def remove_stock(symbol: str):
    """Remove a stock from the portfolio."""
    try:
        result = delete_stock(symbol)
        return result
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


@app.post("/api/report/email")
def email_portfolio_report(background_tasks: BackgroundTasks = None):
    """
    Generate the portfolio PDF report and send it to the default recipient from .env.
    """
    try:
        
        # 1. Fetch current stock data
        stocks_data = get_all_stocks_with_metrics()
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


# Mount Static Files to serve frontend SPA at root "/"
# Check if static directory exists first
static_dir = Path("app/static")
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/", StaticFiles(directory="app/static", html=True), name="static")

