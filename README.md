# 📈 Stock Portfolio Analyser

A full-stack **Stock Portfolio Tracking** web application built with **FastAPI** (Python backend) and a **Vanilla JS SPA** (frontend). It reads and writes stock holdings from an Excel file and fetches real-time prices and moving averages via **Yahoo Finance (`yfinance`)**.

---

## ✨ Features

- 📊 **Portfolio Dashboard** — View all your stock holdings with live prices, P&L, and gain/loss %
- 🔄 **CRUD Operations** — Add, edit, and delete stock transactions
- 📁 **Excel Upload & Merge** — Upload a portfolio Excel file to merge into your existing holdings
- 📉 **SMA Indicators** — 20-day, 100-day, and 200-day Simple Moving Averages for each stock
- 📈 **Historical Charts** — Interactive Chart.js line charts with SMA overlays (1M, 3M, 6M, 1Y, 2Y, 5Y)
- ⚖️ **Weighted Average Price** — Automatically computes weighted average buying price on duplicate entries
- 🌙 **Dark Glassmorphic UI** — Modern, premium SPA with smooth animations
- 🇮🇳 **Indian & US Stocks** — Supports NSE (`RELIANCE.NS`), BSE, and US tickers (`AAPL`, `TSLA`)

---

## 🗂️ Project Structure

```
Stock_Analyser/
├── assets/
│   └── stocks.xlsx          # Portfolio database (auto-created with sample data)
├── app/
│   ├── main.py              # FastAPI app, CORS, and API endpoint definitions
│   ├── services.py          # Excel I/O, yfinance data fetching, SMA calculations
│   └── static/
│       ├── index.html       # Single-Page Application (SPA) HTML
│       ├── style.css        # Dark glassmorphic CSS styling
│       └── app.js           # Vanilla JS — state, API calls, Chart.js charts
├── requirements.txt         # Python dependencies
└── run.py                   # Bootstrap & server launch script
```

---

## 🚀 Getting Started

### Prerequisites

- **Python 3.9+**
- **pip**
- Internet connection (for fetching live stock data via Yahoo Finance)

### 1. Clone the Repository

```bash
git clone https://github.com/your-username/Stock_Analyser.git
cd Stock_Analyser
```

### 2. Create & Activate Virtual Environment

```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# macOS / Linux
python -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Run the Application

```bash
python run.py
```

On first run, a sample portfolio (`assets/stocks.xlsx`) is auto-created with Indian NSE stocks:

| Stock Name   | Buying Price | Quantity |
|--------------|-------------|----------|
| RELIANCE.NS  | 2450.50     | 15       |
| TCS.NS       | 3200.00     | 8        |
| INFY.NS      | 1420.75     | 25       |

Then open your browser at 👉 **[http://127.0.0.1:8000](http://127.0.0.1:8000)**

---

## 📡 API Reference

Base URL: `http://127.0.0.1:8000`

Interactive API docs available at: **[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)**

| Method   | Endpoint                          | Description                                      |
|----------|-----------------------------------|--------------------------------------------------|
| `GET`    | `/api/stocks`                     | Get all stocks with live prices & SMAs           |
| `POST`   | `/api/stocks`                     | Add a new stock (merges if symbol already exists)|
| `PUT`    | `/api/stocks/{symbol}`            | Directly update price & quantity for a stock     |
| `DELETE` | `/api/stocks/{symbol}`            | Remove a stock from the portfolio                |
| `GET`    | `/api/stocks/{symbol}/history`    | Fetch historical price data for charting         |
| `POST`   | `/api/stocks/upload`              | Upload an Excel file to merge into portfolio     |

### Example: Add a Stock

```bash
curl -X POST "http://127.0.0.1:8000/api/stocks" \
  -H "Content-Type: application/json" \
  -d '{"symbol": "AAPL", "price": 185.50, "quantity": 10}'
```

### Valid History Periods

`1mo` | `3mo` | `6mo` | `1y` | `2y` | `5y`

---

## 📊 Excel File Format

The portfolio is stored in `assets/stocks.xlsx`. The file must contain these three columns:

| Column       | Type   | Description                         |
|--------------|--------|-------------------------------------|
| `Stock Name` | string | Ticker symbol (e.g. `RELIANCE.NS`)  |
| `Buying Price` | float | Average purchase price per share   |
| `Quantity`   | float  | Number of shares held               |

> **💡 Tip:** You can upload your own Excel file from the UI. If a stock symbol already exists, the app merges it using a **weighted average buying price**.

---

## 📐 SMA Calculation Logic

Simple Moving Averages are computed using the last **250 trading days** of historical close price data fetched via `yfinance`.

| Indicator | Window       |
|-----------|-------------|
| SMA 20    | 20 trading days  |
| SMA 100   | 100 trading days |
| SMA 200   | 200 trading days |

Calculated using `pandas`: `df['Close'].rolling(window=N).mean()`

---

## 🧩 Stock Symbol Format

| Exchange              | Format Examples                          |
|-----------------------|------------------------------------------|
| 🇮🇳 NSE (India)       | `RELIANCE.NS`, `TCS.NS`, `INFY.NS`       |
| 🇮🇳 BSE (India)       | `RELIANCE.BO`, `TCS.BO`                  |
| 🇺🇸 US Markets         | `AAPL`, `TSLA`, `MSFT`, `GOOGL`          |

---

## 🛠️ Tech Stack

| Layer     | Technology                                    |
|-----------|-----------------------------------------------|
| Backend   | [FastAPI](https://fastapi.tiangolo.com/) + [Uvicorn](https://www.uvicorn.org/) |
| Data      | [yfinance](https://pypi.org/project/yfinance/) + [pandas](https://pandas.pydata.org/) |
| Storage   | Excel (`.xlsx`) via [openpyxl](https://openpyxl.readthedocs.io/) |
| Frontend  | Vanilla HTML + CSS + JavaScript              |
| Charts    | [Chart.js](https://www.chartjs.org/)          |
| Fonts     | Google Fonts (Inter, Outfit)                  |
| Icons     | FontAwesome                                   |

---

## 📦 Dependencies

```
fastapi>=0.100.0
uvicorn>=0.22.0
pandas>=2.0.0
openpyxl>=3.1.0
yfinance>=0.2.20
python-multipart>=0.0.6
pydantic>=2.0.0
```

---

## 🤝 Contributing

1. Fork the repo
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Commit your changes: `git commit -m 'Add amazing feature'`
4. Push to the branch: `git push origin feature/amazing-feature`
5. Open a Pull Request

---

## 📄 License

This project is open-source and available under the [MIT License](LICENSE).

---

> Built with ❤️ using FastAPI & yfinance
