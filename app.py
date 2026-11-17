"""
Momentum + EMA20 Retest - live screener (Nifty 500)
Run locally :  streamlit run app.py
Phone (same Wi-Fi) : open  http://<laptop-IP>:8501
Anywhere    :  deploy free on Streamlit Community Cloud (see README.md)
"""
import io
import os
from datetime import datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st

import screener_core as core

IST = ZoneInfo("Asia/Kolkata")
HERE = Path(__file__).parent
OFFLINE_CSV = os.environ.get("SCREENER_CSV")          # optional: use local data file

st.set_page_config(page_title="Momentum Retest Screener", page_icon="📈", layout="wide")
st.markdown("""<style>
.block-container{padding-top:1.2rem;padding-bottom:2rem}
div[data-testid="stMetricValue"]{font-size:1.6rem}
@media (max-width:640px){.block-container{padding-left:.6rem;padding-right:.6rem}
 h1{font-size:1.4rem!important}}
</style>""", unsafe_allow_html=True)


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
        for s, t in zip(batch, tick):
            try:
                g = raw[t] if len(tick) > 1 else raw
                g = g.rename(columns=str.lower)[["open", "high", "low", "close"]].dropna()
                g.index = pd.to_datetime(g.index).tz_localize(None)
                if len(g) >= 60:
                    out[s] = g
                else:
                    failed.append(s)
            except Exception:
                failed.append(s)
    return out, failed


def market_open_now():
    now = datetime.now(IST)
    return now.weekday() < 5 and dtime(9, 15) <= now.time() <= dtime(15, 30)


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.header("⚙️ Settings")
    capital = st.number_input("Capital (₹)", 10000, 100_000_000, 100000, step=10000)
    risk = st.number_input("Risk per trade (%)", 0.1, 5.0, 1.0, step=0.1)
    live = market_open_now()
    use_live = st.toggle("Use today's live candle", value=False,
                         help="Rules are based on completed daily candles. Keep OFF during "
                              "market hours; turn ON only to preview today's possible setups.")
    if st.button("🔄 Refresh data", width="stretch"):
        load_prices.clear()
        st.rerun()
    st.caption("Data: Yahoo Finance (may be ~15 min delayed). Cached 15 min.")

# ------------------------------------------------------------------ run
st.title("📈 Momentum + EMA20 Retest Screener")
uni, uni_src = load_universe()
names = dict(zip(uni["Symbol"], uni["Company Name"]))
with st.spinner("Downloading Nifty 500 prices… (first load ~30–60 s)"):
    prices, failed = load_prices(tuple(sorted(uni["Symbol"])))

if not prices:
    st.error("Could not download price data. Check your internet connection and refresh.")
    st.stop()

today = datetime.now(IST).date()
latest_bar = max(p.index[-1] for p in prices.values()).date()
live_px = {s: p.close.iloc[-1] for s, p in prices.items()}
live_hi = {s: p.high.iloc[-1] for s, p in prices.items()}
scan_prices = prices
partial = latest_bar == today and live and not OFFLINE_CSV
if partial and not use_live:
    scan_prices = {s: p[p.index.date < today] for s, p in prices.items()}

res = core.scan_universe(scan_prices, capital, risk)
scan_date = max(p.index[-1] for p in scan_prices.values()).date()

st.caption(f"Signals based on candles up to **{scan_date:%d %b %Y}** · "
           f"{len(prices)} stocks · {uni_src}"
           + (" · 🟢 market open, live prices shown" if partial else "")
           + (f" · {len(failed)} symbols unavailable" if failed else ""))

if res.empty:
    st.info("No stocks currently meet the criteria.")
    st.stop()

res["company"] = res.symbol.map(names)
if partial:
    res["live"] = res.symbol.map(live_px).round(2)

buy = res[res.status == "BUY-STOP ACTIVE"].copy()
trade = res[res.status.isin(["IN TRADE", "EXIT AT NEXT OPEN"])].copy()
watch = res[res.status == "WATCHLIST"].copy()
closed = res[res.status.isin(["STOPPED", "CLOSED (EMA20)", "CLOSED (40 days)"])].copy()

if partial and len(buy):
    buy["triggered_today"] = buy.apply(
        lambda r: "✅ YES" if live_hi.get(r.symbol, 0) > r.buy_above else "—", axis=1)

n_exit = int((trade.status == "EXIT AT NEXT OPEN").sum())
boxes = [("🟢 Buy-stop", len(buy)), ("📈 In trade", len(trade)),
         ("🚪 Exit", n_exit), ("👀 Watchlist", len(watch))]
st.markdown(
    '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:4px 0 10px">'
    + "".join(f'<div style="border:1px solid rgba(128,128,128,.3);border-radius:10px;'
              f'padding:8px 6px;text-align:center"><div style="font-size:.78rem;opacity:.75">{k}</div>'
              f'<div style="font-size:1.5rem;font-weight:700">{v}</div></div>' for k, v in boxes)
    + "</div>", unsafe_allow_html=True)


def show(df, cols, rename):
    cols = [c for c in cols if c in df]
    st.dataframe(df[cols].convert_dtypes().rename(columns=rename), hide_index=True, width="stretch")


t1, t2, t3, t4 = st.tabs(["🟢 Buy-stop", "📈 Trades / Exit", "👀 Watchlist", "📘 Rules"])

with t1:
    st.caption("Retest candle formed. Place a **buy-stop just above 'Buy above'**, "
               "SL at 'Stop loss'. Order valid for 'Days left' trading days.")
    if len(buy):
        show(buy.sort_values("risk_pct"),
             ["symbol", "buy_above", "stop_loss", "qty", "valid_days_left", "triggered_today", "live",
              "risk_pct", "position_value", "setup_date", "event_date", "week_move_%", "company"],
             {"symbol": "Stock", "company": "Company", "buy_above": "Buy above", "stop_loss": "Stop loss",
              "risk_pct": "Risk %", "qty": "Qty", "position_value": "Value ₹",
              "valid_days_left": "Days left", "triggered_today": "Triggered?", "live": "Live",
              "setup_date": "Setup", "event_date": "20% week", "week_move_%": "Week move %"})
    else:
        st.info("No active buy-stop setups today.")

with t2:
    st.caption("**EXIT AT NEXT OPEN** = closed below EMA20 → sell at tomorrow's open. "
               "Otherwise hold; SL = setup low.")
    if len(trade):
        trade["action"] = trade.status.map({"IN TRADE": "Hold", "EXIT AT NEXT OPEN": "🚪 SELL at open"})
        show(trade.sort_values("status"),
             ["symbol", "action", "pnl_pct", "stop_loss", "ema20", "close", "live", "entry",
              "days_held", "entry_date"],
             {"symbol": "Stock", "action": "Action", "entry": "Entry", "stop_loss": "SL",
              "close": "Close", "ema20": "EMA20", "pnl_pct": "P&L %", "days_held": "Days",
              "entry_date": "Entry date", "live": "Live"})
        st.caption("Shows trades a rule-follower would be in. Exit after 40 trading days if still open.")
    else:
        st.info("No open trades per the rules.")
    if len(closed):
        with st.expander(f"Recently closed ({len(closed)})"):
            show(closed, ["symbol", "status", "entry", "stop_loss", "close", "pnl_pct", "exit_date"],
                 {"symbol": "Stock", "status": "Result", "entry": "Entry", "stop_loss": "SL",
                  "close": "Close", "pnl_pct": "P&L %", "exit_date": "Exit"})

with t3:
    st.caption("Made a clean 20%+ week, trend up. Waiting for a dip to EMA20 "
               "(low ≤ EMA20, close above it).")
    if len(watch):
        watch["new"] = watch.new_event_today.map({True: "🆕", False: ""})
        show(watch.sort_values("dist_to_ema20_pct"),
             ["symbol", "new", "dist_to_ema20_pct", "days_left", "close", "live", "event_date",
              "week_move_%", "company"],
             {"symbol": "Stock", "new": "", "company": "Company", "close": "Close",
              "dist_to_ema20_pct": "% above EMA20", "days_left": "Days left",
              "event_date": "20% week", "week_move_%": "Week move %", "live": "Live"})
    else:
        st.info("Watchlist is empty.")

with t4:
    st.markdown(f"""
**1. Find** – Nifty 500 stock up **≥ 20 % in 5 trading days**, no single day more than half
of the move, close > EMA20 > EMA50.

**2. Watch** – for **20 trading days**. Drop it if it closes below EMA50.

**3. Setup** – a candle that **dips to EMA20 (low ≤ EMA20) and closes above it**.

**4. Entry** – **buy-stop above the setup high**, valid **3 days**.

**5. Stop-loss** – setup-candle low.

**6. Size** – qty = ₹{capital * risk / 100:,.0f} (= {risk}% of ₹{capital:,.0f}) ÷ (entry − SL).
If cash is short, buy what you can; skip if you can't buy 1 share.

**7. Exit** – **no fixed target**. Sell at next open after a **close below EMA20**, or at SL,
or after **40 trading days**.

*Backtest Dec 2023 – Nov 2026, ₹1 lakh, 1 % risk: ~25.8 % CAGR, max drawdown −21 %,
win rate 38 %. Past results don't guarantee future returns; research tool, not advice.*
""")

st.download_button("⬇️ Download all results (CSV)", res.to_csv(index=False).encode(),
                   f"screener_{scan_date}.csv", "text/csv", width="stretch")
