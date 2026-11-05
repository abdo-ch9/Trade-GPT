"""Market/news ingestion. Only read-only data endpoints; NO brokerage order calls."""
from __future__ import annotations
import os
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()
BASE = "https://data.alpaca.markets"


def headers():
    key, secret = os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_API_SECRET")
    if not key or not secret or key.startswith("YOUR_"):
        raise RuntimeError("Set ALPACA_API_KEY and ALPACA_API_SECRET in .env (data access).")
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


def paginated(endpoint, params, root_name, max_pages=1000):
    out, token = [], None
    with requests.Session() as session:
        session.headers.update(headers())
        for _ in range(max_pages):
            query = dict(params)
            if token:
                query["page_token"] = token
            response = session.get(BASE + endpoint, params=query, timeout=30)
            response.raise_for_status()
            payload = response.json()
            out.extend(payload.get(root_name, []))
            token = payload.get("next_page_token")
            if not token:
                return out
    raise RuntimeError("Pagination hit max_pages; narrow the requested date range.")


def fetch_bars(symbol, start, end, feed="iex"):
    data = paginated(f"/v2/stocks/{symbol.upper()}/bars", dict(start=start, end=end, timeframe="1Min", adjustment="raw", feed=feed, limit=10000), "bars")
    df = pd.DataFrame(data)
    if df.empty:
        raise ValueError("No bars returned; check symbol, dates, permissions, market hours.")
    df = df.rename(columns={"t":"timestamp", "o":"open", "h":"high", "l":"low", "c":"close", "v":"volume", "vw":"vwap", "n":"trades"})
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df.sort_values("timestamp").drop_duplicates("timestamp")


def fetch_news(symbol, start, end):
    df = pd.DataFrame(paginated("/v1beta1/news", dict(symbols=symbol.upper(), start=start, end=end, limit=50, sort="asc"), "news"))
    if df.empty:
        return pd.DataFrame(columns=["created_at", "headline", "summary", "symbols"])
    return df.drop_duplicates("id" if "id" in df.columns else "headline")


def save_csv(df, filename):
    path = Path(filename); path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    print(f"Wrote {len(df):,} rows to {path}")
