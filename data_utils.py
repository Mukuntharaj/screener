"""Shared data loading for the screener pages (Yahoo Finance + NSE lists)."""
import io
import os
from datetime import datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st

IST = ZoneInfo("Asia/Kolkata")
HERE = Path(__file__).parent
OFFLINE_CSV = os.environ.get("SCREENER_CSV")          # optional: use local data file


# ------------------------------------------------------------------ universe
@st.cache_data(ttl=7 * 24 * 3600, show_spinner=False)
def load_universe():
    urls = ["https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv",
            "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"]
    hdr = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0"}
    if not OFFLINE_CSV:
        for u in urls:
            try:
                r = requests.get(u, headers=hdr, timeout=10)
                if r.ok:
                    df = pd.read_csv(io.BytesIO(r.content))
                    df.columns = [c.strip() for c in df.columns]
                    if "Symbol" in df and len(df) > 400:
                        return df[["Symbol", "Company Name", "Industry"]], "live list"
            except Exception:
                pass
    return pd.read_csv(HERE / "nifty500.csv"), "bundled list"


# ------------------------------------------------------------------ prices
@st.cache_data(ttl=15 * 60, show_spinner=False)
def load_prices(symbols):
    if OFFLINE_CSV:
        d = pd.read_csv(OFFLINE_CSV, parse_dates=["date"])
        if "series" in d:
            d = d[d.series == "EQ"]
        d = d[d.symbol.isin(symbols)].sort_values(["symbol", "date"])
        return {s: g.set_index("date")[["open", "high", "low", "close"]]
                for s, g in d.groupby("symbol")}, []
    import yfinance as yf
    out, failed = {}, []
    syms = list(symbols)
    for i in range(0, len(syms), 100):
        batch = syms[i:i + 100]
        tick = [s + ".NS" for s in batch]
        try:
            raw = yf.download(tick, period="1y", interval="1d", auto_adjust=True,
                              group_by="ticker", threads=True, progress=False)
        except Exception:
            failed += batch
            continue
        # Yahoo sometimes publishes the latest NSE daily candle late.
        # Hourly candles of the last few days are used to fill any gap.
        try:
            hourly = yf.download(tick, period="5d", interval="60m", auto_adjust=True,
                                 group_by="ticker", threads=True, progress=False)
        except Exception:
            hourly = None
        for s, t in zip(batch, tick):
            try:
                g = raw[t] if len(tick) > 1 else raw
                g = g.rename(columns=str.lower)[["open", "high", "low", "close"]].dropna()
                g.index = _to_ist_dates(g.index)
                if hourly is not None:
                    hh = hourly[t] if len(tick) > 1 else hourly
                    g = fill_from_hourly(g, hh)
                if len(g) >= 60:
                    out[s] = g
                else:
                    failed.append(s)
            except Exception:
                failed.append(s)
    return out, failed


def _to_ist_dates(idx):
    idx = pd.to_datetime(idx)
    if idx.tz is not None:
        idx = idx.tz_convert(IST).tz_localize(None)
    return idx.normalize()


def session_complete(day):
    """True if the NSE session on `day` has finished (after 15:30 IST)."""
    now = datetime.now(IST)
    return day < now.date() or (day == now.date() and now.time() >= dtime(15, 30))


def fill_from_hourly(daily, hourly):
    """Append completed sessions that exist in hourly data but not in daily."""
    h = hourly.rename(columns=str.lower)[["open", "high", "low", "close"]].dropna()
    if h.empty:
        return daily
    h.index = pd.to_datetime(h.index)
    if h.index.tz is not None:
        h.index = h.index.tz_convert(IST).tz_localize(None)
    agg = h.groupby(h.index.normalize()).agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"))
    last = daily.index.max() if len(daily) else pd.Timestamp.min
    new = agg[(agg.index > last) & [session_complete(d.date()) for d in agg.index]]
    if new.empty:
        return daily
    new = new.assign(filled=True)
    return pd.concat([daily.assign(filled=False), new]).sort_index()


def market_open_now():
    now = datetime.now(IST)
    return now.weekday() < 5 and dtime(9, 15) <= now.time() <= dtime(15, 30)


# ------------------------------------------------------------------ F&O list
@st.cache_data(ttl=7 * 24 * 3600, show_spinner=False)
def load_fo_universe():
    """NSE F&O stock list: live from NSE if reachable, else bundled fo_stocks.csv."""
    hdr = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0",
           "Referer": "https://www.nseindia.com/"}
    if not OFFLINE_CSV:
        for u in ("https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv",
                  "https://archives.nseindia.com/content/fo/fo_mktlots.csv"):
            try:
                r = requests.get(u, headers=hdr, timeout=10)
                if r.ok:
                    df = pd.read_csv(io.BytesIO(r.content))
                    df.columns = [c.strip().upper() for c in df.columns]
                    sym = df["SYMBOL"].astype(str).str.strip()
                    und = df.get("UNDERLYING", sym).astype(str).str.strip()
                    idx = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "SYMBOL"}
                    keep = ~sym.isin(idx) & ~und.str.upper().str.contains("NIFTY")
                    out = pd.DataFrame({"Symbol": sym[keep], "Company Name": und[keep]})
                    if len(out) > 150:
                        return out.drop_duplicates("Symbol").reset_index(drop=True), "live NSE list"
            except Exception:
                pass
    return pd.read_csv(HERE / "fo_stocks.csv"), "bundled list (Nov 2026)"


@st.cache_data(ttl=5 * 60, show_spinner=False)
def load_intraday(symbols, interval="15m", period="1mo"):
    """Intraday OHLC per symbol, index = naive IST timestamps (bar start)."""
    import yfinance as yf
    out, failed = {}, []
    syms = list(symbols)
    for i in range(0, len(syms), 75):
        batch = syms[i:i + 75]
        tick = [s + ".NS" for s in batch]
        try:
            raw = yf.download(tick, period=period, interval=interval, auto_adjust=True,
                              group_by="ticker", threads=True, progress=False)
        except Exception:
            failed += batch
            continue
        for s, t in zip(batch, tick):
            try:
                g = raw[t] if len(tick) > 1 else raw
                g = g.rename(columns=str.lower)[["open", "high", "low", "close"]].dropna()
                g.index = pd.to_datetime(g.index)
                if g.index.tz is not None:
                    g.index = g.index.tz_convert(IST).tz_localize(None)
                g = g[(g.index.time >= dtime(9, 15)) & (g.index.time < dtime(15, 30))]
                if len(g) > 20:
                    out[s] = g
                else:
                    failed.append(s)
            except Exception:
                failed.append(s)
    return out, failed
