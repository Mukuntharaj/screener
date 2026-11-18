"""Page 1 - Momentum + EMA20 retest screener (Nifty 500, daily candles)."""
from datetime import datetime

import pandas as pd
import streamlit as st

import screener_core as core
from data_utils import (IST, OFFLINE_CSV, load_universe, load_prices,
                        session_complete, market_open_now)

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.header("⚙️ Settings")
    capital = st.number_input("Capital (₹)", 10000, 100_000_000, 100000, step=10000)
    risk = st.number_input("Risk per trade (%)", 0.1, 5.0, 1.0, step=0.1)
    live = market_open_now()
    use_live = st.toggle("Preview with today's unfinished candle", value=False,
                         help="Keep OFF. The rules use completed daily candles. ON only "
                              "previews possible setups during market hours - they can "
                              "disappear by the close.")
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

# expected latest completed session (weekends skipped; NSE holidays not known)
exp = datetime.now(IST).date()
while not session_complete(exp) or exp.weekday() >= 5:
    exp -= pd.Timedelta(days=1)
n_filled = sum(bool(p["filled"].iloc[-1]) for p in prices.values() if "filled" in p)
if partial and use_live:
    st.warning("⚠️ PREVIEW MODE: signals use today's unfinished candle and may disappear "
               "by the close. Switch the toggle off for real signals.")
if scan_date < exp and not OFFLINE_CSV and not (partial and use_live):
    st.warning(f"Data ends **{scan_date:%d %b}** but the last completed session should be "
               f"**{exp:%d %b}** (unless it was an NSE holiday). Yahoo hasn't published it yet - "
               "tap **Refresh data** later.")
if n_filled:
    st.info(f"Latest candle for {n_filled} stocks was built from Yahoo hourly data "
            "(daily candle not yet published). Close may differ slightly from NSE's official close.")
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
