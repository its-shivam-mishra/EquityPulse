import sys
from pathlib import Path

# Add project root to sys.path to resolve app imports
sys.path.append(str(Path(__file__).parent.resolve()))

import pandas as pd
import uvicorn

ASSETS_DIR = Path("assets")
EXCEL_PATH = ASSETS_DIR / "stocks.xlsx"

def bootstrap_data():
    """Create directory structure and seed database Excel file with sample NSE data if it doesn't exist."""
    print("Bootstrapping Stock Analyser project...")
    
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    
    if not EXCEL_PATH.exists():
        print("Excel sheet 'assets/stocks.xlsx' not found. Creating a sample portfolio...")
        
        # Sample holdings with Indian (NSE) symbols
        sample_data = {
            "Stock Name": ["RELIANCE.NS", "TCS.NS", "INFY.NS"],
            "Buying Price": [2450.50, 3200.00, 1420.75],
            "Quantity": [15, 8, 25]
        }
        
        df = pd.DataFrame(sample_data)
        df.to_excel(EXCEL_PATH, index=False)
        print(f"Sample portfolio successfully created at: {EXCEL_PATH.resolve()}")
    else:
        print(f"Portfolio database already exists at: {EXCEL_PATH.resolve()}")

if __name__ == "__main__":
    bootstrap_data()
    print("Starting FastAPI Backend Server...")
    print("Open http://127.0.0.1:8000 in your browser to view the application.")
    
    # Run the uvicorn server
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
