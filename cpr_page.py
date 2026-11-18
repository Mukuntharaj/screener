"""Page 2 - F&O intraday double/triple bottom-top screener around CPR, S1 and R1."""
from datetime import datetime

import pandas as pd
import streamlit as st

import cpr_core as cc
from data_utils import (IST, load_fo_universe, load_prices, load_intraday,
                        session_complete, market_open_now)

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.header("⚙️ Pattern settings")
    interval = st.radio("Chart timeframe", ["15m", "1h"], horizontal=True,
                        format_func=lambda v: "15 min" if v == "15m" else "1 hour")
    filt = st.selectbox("Daily trend filter", list(cc.FILTERS), index=0)
    kinds = st.multiselect("Patterns", ["bottom", "top"], default=["bottom", "top"],
                           format_func=lambda k: "Bottoms below CPR at S1" if k == "bottom"
                           else "Tops above CPR below R1")
    days = st.slider("Chart days", 10, 20, 10)
    p = cc.PARAMS[interval]
    with st.expander("Fine-tune detection"):
        tol = st.slider("Equal lows/highs tolerance (%)", 0.1, 1.5, p.tol, 0.05)
        lvl_tol = st.slider("Max distance from S1 / above R1 (%)", 0.1, 2.0, p.lvl_tol, 0.05)
    if st.button("🔄 Refresh data", width="stretch"):
        load_intraday.clear()
        load_prices.clear()
        st.rerun()
    st.caption("Data: Yahoo Finance, ~15 min delayed. Intraday cached 5 min.")

# ------------------------------------------------------------------ data
st.title("🎯 F&O CPR Pattern Screener")
fo, fo_src = load_fo_universe()
syms = tuple(sorted(fo["Symbol"]))
names = dict(zip(fo["Symbol"], fo["Company Name"]))

with st.spinner(f"Downloading {len(syms)} F&O stocks: daily + {interval} candles… (~30–60 s)"):
    daily_map, _ = load_prices(syms)
    intra_map, failed = load_intraday(syms, interval, "1mo")

if not intra_map:
    st.error("Could not download intraday data. Check the connection and refresh.")
    st.stop()

ref = max(intra_map.values(), key=len)
all_days = sorted(set(ref.index.date))
done_days = [d for d in all_days if session_complete(d)]
last_complete = done_days[-1] if done_days else all_days[0]
latest_bar = max(g.index[-1] for g in intra_map.values())

res, trend_ok = cc.scan(intra_map, daily_map, interval, filt, last_complete,
                        tol=tol, lvl_tol=lvl_tol, kinds=tuple(kinds))

live_txt = " · 🟢 market open" if market_open_now() else ""
st.caption(f"Latest {interval} candle **{latest_bar:%d %b %H:%M}**{live_txt} · trend filter on "
           f"**{last_complete:%d %b}** daily close · {len(intra_map)} F&O stocks ({fo_src}) · "
           f"{len(trend_ok)} pass the trend filter"
           + (f" · {len(failed)} unavailable" if failed else ""))

bots = res[res.pattern.str.contains("bottom")] if len(res) else res
tops = res[res.pattern.str.contains("top")] if len(res) else res
n_brk = int(res.status.isin(["BREAKOUT", "BREAKDOWN"]).sum()) if len(res) else 0
boxes = [("🟢 Bottoms", len(bots)), ("🔴 Tops", len(tops)), ("⚡ Neckline crossed", n_brk),
         ("📈 Trend OK", len(trend_ok))]
st.markdown(
    '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:4px 0 10px">'
    + "".join(f'<div style="border:1px solid rgba(128,128,128,.3);border-radius:10px;'
              f'padding:8px 6px;text-align:center"><div style="font-size:.78rem;opacity:.75">{k}</div>'
              f'<div style="font-size:1.5rem;font-weight:700">{v}</div></div>' for k, v in boxes)
    + "</div>", unsafe_allow_html=True)


def table(df, side):
    if df.empty:
        st.info("No stocks match right now.")
        return
    t = pd.DataFrame({
        "Stock": df.symbol,
        "Pattern": df.pattern,
        "Status": df.status.map({"FORMING": "⏳ Forming", "BREAKOUT": "✅ Breakout",
                                 "BREAKDOWN": "✅ Breakdown"}),
        ("Buy above" if side == "bottom" else "Sell below"): df.neckline.round(2),
        "SL": df.sl.round(2), "T1": df.t1.round(2), "T2": df.t2.round(2),
        "Last": df["last"].round(2),
        ("Pattern low" if side == "bottom" else "Pattern high"): df.level.round(2),
        ("S1" if side == "bottom" else "R1"): (df.S1 if side == "bottom" else df.R1).round(2),
        "CPR": df.BC.round(1).astype(str) + "–" + df.TC.round(1).astype(str),
        "Last point": df.points.map(lambda p: p[-1].strftime("%d %b %H:%M")),
        "Company": df.symbol.map(names),
    })
    st.dataframe(t.sort_values("Status"), hide_index=True, width="stretch")


t1, t2, t3, t4 = st.tabs(["🟢 Bottoms @ S1", "🔴 Tops below R1", "📊 Charts", "📘 Rules"])
with t1:
    st.caption("2–3 equal lows **below CPR at S1**. Trigger: close above the neckline "
               "(Buy above). Targets = next CPR levels above.")
    table(bots, "bottom")
with t2:
    st.caption("2–3 equal highs **above CPR, below R1**. Trigger: close below the neckline "
               "(Sell below). Targets = next CPR levels below.")
    table(tops, "top")

with t3:
    if len(res):
        order = res.assign(crossed=res.status != "FORMING",
                           t=res.points.map(lambda p: p[-1])).sort_values(["crossed", "t"],
                                                                          ascending=False)
        matched = list(dict.fromkeys(order.symbol))
    else:
        matched = []
    opts = matched + [s for s in sorted(intra_map) if s not in matched]
    if not opts:
        st.info("No data to chart.")
    else:
        sym = st.selectbox(f"Stock ({len(matched)} with patterns listed first)", opts,
                           format_func=lambda s: f"{'⭐ ' if s in matched else ''}{s}")
        view = st.segmented_control("View", [f"{days} days", "Pattern zoom (2 days)"],
                                    default=f"{days} days")
        days_shown = 2 if view and view.startswith("Pattern") else days
        pats = res[res.symbol == sym].to_dict("records") if len(res) else []
        if sym in daily_map:
            fig = cc.chart(sym, intra_map[sym], daily_map[sym], last_complete, days_shown,
                           pats[0] if pats else None)
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
            if len(pats) > 1:
                fig2 = cc.chart(sym, intra_map[sym], daily_map[sym], last_complete, days_shown, pats[1])
                st.plotly_chart(fig2, width="stretch", config={"displayModeBar": False})
            if pats:
                for pt in pats:
                    st.markdown(f"**{pt['pattern']}** · {pt['status'].title()} · neckline "
                                f"**{pt['neckline']:.2f}** · SL {pt['sl']:.2f} · "
                                f"T1 {pt['t1']:.2f} · T2 {pt['t2']:.2f}")
            st.caption("Blue band = CPR (BC–TC), blue dots = pivot P, red dashes = R1, "
                       "green dashes = S1 (levels change each day). Orange = neckline, "
                       "purple ▲/▼ = pattern lows/highs.")
        else:
            st.warning("No daily data for this stock.")
        if matched and st.toggle(f"Show all {len(matched)} pattern charts", value=False):
            for s in matched:
                if s == sym or s not in daily_map:
                    continue
                for pt in res[res.symbol == s].to_dict("records"):
                    st.plotly_chart(cc.chart(s, intra_map[s], daily_map[s], last_complete, days_shown, pt,
                                             height=380), width="stretch",
                                    config={"displayModeBar": False})

with t4:
    st.markdown(f"""
**Universe** – NSE F&O stocks only ({len(fo)} stocks, {fo_src}).

**Daily filter** – latest completed daily candle: *{filt}*.

**CPR** (from the previous session's high, low, close)
P = (H+L+C)/3 · BC = (H+L)/2 · TC = 2P − BC · R1 = 2P − L · S1 = 2P − H

**Bottom (bullish)** – on {'15-min' if interval == '15m' else '1-hour'} candles:
2 or 3 swing lows within **{tol:.2f}%** of each other, each **below the CPR** of its day
and within **{lvl_tol:.2f}%** of **S1**, with a bounce of at least {p.min_depth}% between them.
Neckline = highest point between the lows.
➜ Entry on a close **above the neckline** · SL below the lowest low · targets = BC/P/TC/R1 above.

**Top** – 2 or 3 swing highs within {tol:.2f}% of each other, each **above the CPR**
and **below R1** (up to {lvl_tol:.2f}% tolerance).
Neckline = lowest point between the highs.
➜ Trigger on a close **below the neckline** · SL above the highest high · targets = TC/P/BC/S1 below.

**Status** – ⏳ Forming = neckline not crossed yet · ✅ Breakout/Breakdown = a candle has
closed beyond the neckline.

*Pattern recognition is mechanical – always confirm on the chart. Intraday data from Yahoo
is ~15 min delayed. This is a screening tool, not a backtested strategy or advice.*
""")

st.download_button("⬇️ Download results (CSV)", res.drop(columns=["points"], errors="ignore")
                   .to_csv(index=False).encode() if len(res) else b"",
                   f"fo_cpr_patterns_{datetime.now(IST):%Y%m%d_%H%M}.csv", "text/csv",
                   width="stretch", disabled=res.empty)
