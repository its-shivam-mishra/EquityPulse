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

@app.on_event("startup")
def startup_event():
    from app.cosmos_service import cosmos_service
    # Initializes Cosmos DB on module load
    _ = cosmos_service.get_all_stocks()
    
    # Migrate data from Excel if Cosmos DB is empty
    from pathlib import Path
    import pandas as pd
    excel_path = Path("assets/stocks.xlsx")
    if excel_path.exists():
        try:
            items = cosmos_service.get_all_stocks()
            if not items:
                df = pd.read_excel(excel_path)
                from app.services import write_stocks
                write_stocks(df)
                print("Migrated existing Excel data to Cosmos DB.")
        except Exception as e:
            print(f"Error during migration check: {e}")

# Pydantic Schemas for Requests
class StockTransaction(BaseModel):
    company_name: str = Field(..., description="Human readable company name")
    stock_code: str = Field(..., description="Base ticker symbol (e.g. RELIANCE, TCS)")
    exchange: str = Field(..., description="Exchange abbreviation (e.g. NSE, BSE)")
    price: float = Field(..., gt=0, description="Purchase price per share")
    quantity: float = Field(..., gt=0, description="Quantity of shares purchased")

class StockDetailsUpdateData(BaseModel):
    company_name: str = Field(..., description="New company name")
    stock_code: str = Field(..., description="New base ticker symbol")
    exchange: str = Field(..., description="New exchange")

class StockUpdateData(BaseModel):
    company_name: str = Field(..., description="New company name")
    stock_code: str = Field(..., description="New base ticker symbol")
    exchange: str = Field(..., description="New exchange")
    price: float = Field(..., gt=0, description="New average buying price per share")
    quantity: float = Field(..., gt=0, description="New quantity of shares")

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
        result = add_stock(
            company_name=transaction.company_name,
            stock_code=transaction.stock_code,
            exchange=transaction.exchange,
            price=transaction.price,
            quantity=transaction.quantity
        )
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
    """Directly update price, quantity, and metadata of a stock in the Excel sheet."""
    try:
        result = update_stock(symbol, data.price, data.quantity, data.company_name, data.stock_code, data.exchange)
        return result
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")

@app.put("/api/stocks/{symbol}/details")
def update_stock_details_endpoint(symbol: str, data: StockDetailsUpdateData):
    """Update only the details (name, code, exchange) of a stock."""
    try:
        result = update_stock_details(symbol, data.company_name, data.stock_code, data.exchange)
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

