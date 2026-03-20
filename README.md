# Wheel Strategy Scanner

Options wheel strategy scanner for cash-secured puts and covered calls.

## Features
- Scans S&P 500 stocks for wheel opportunities
- Generates CSV output with trade recommendations
- REST API for programmatic access

## Endpoints

- \GET /\ - API information
- \GET /scan\ - Run scanner (returns JSON with CSV download link)
- \GET /download?file=filename.csv\ - Download CSV file
- \GET /health\ - Health check

## Local Development

\\\ash
pip install -r requirements.txt
python server.py
\\\

Visit http://localhost:5000/scan to run the scanner.

## Deploy to Railway

1. Push to GitHub
2. Connect to Railway
3. Auto-deploys on push
