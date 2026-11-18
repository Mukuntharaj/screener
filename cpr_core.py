"""
F&O intraday pattern screener - logic and charts.

Daily CPR (from the previous session's high/low/close):
    P  = (H + L + C) / 3       BC = (H + L) / 2       TC = 2P - BC   (TC >= BC)
    R1 = 2P - L                S1 = 2P - H

Patterns on 15-min or 1-hour candles (confirmed swing points):
  BOTTOM  2-3 swing lows at ~equal price (within tolerance), each BELOW the CPR
          of its day and NEAR S1 (within S1/R1 distance), a real bounce between
          them, latest low recent. Neckline = highest high between the lows.
  TOP     2-3 swing highs at ~equal price, each ABOVE the CPR and BELOW R1.
          Neckline = lowest low between the highs.
Status: FORMING (neckline not crossed yet) / BREAKOUT (close above neckline,
bottoms) / BREAKDOWN (close below neckline, tops).

Daily filter: latest completed daily candle vs EMA20 / EMA50 (mode selectable).
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

try:
    import plotly.graph_objects as go
except ImportError:          # charts optional for headless use
    go = None


@dataclass
class Params:
    k: int            # bars each side for a swing point
    tol: float        # % equal-low / equal-high tolerance
    min_gap: int      # min bars between swing points
    min_depth: float  # % bounce between the lows (or dip between highs)
    lvl_tol: float    # % distance allowed from S1 (bottoms) / above R1 (tops)
    lookback: int     # bars searched for the pattern
    recent: int       # latest swing point must be within this many bars


PARAMS = {
    "15m": Params(k=3, tol=0.35, min_gap=4, min_depth=0.6, lvl_tol=0.5, lookback=75, recent=25),
    "1h": Params(k=2, tol=0.5, min_gap=3, min_depth=1.0, lvl_tol=0.75, lookback=35, recent=14),
}

FILTERS = {
    "Close above EMA20 and EMA50": lambda r: r.close > r.ema20 and r.close > r.ema50,
    "Close above EMA20 or EMA50": lambda r: r.close > r.ema20 or r.close > r.ema50,
    "Close above EMA20": lambda r: r.close > r.ema20,
    "Close above EMA50": lambda r: r.close > r.ema50,
    "Whole candle above EMA20 and EMA50": lambda r: r.low > max(r.ema20, r.ema50),
}


# --------------------------------------------------------------------- levels
def session_ohlc(daily, intraday, last_complete_day):
    """Daily OHLC for CPR: Yahoo daily, plus sessions built from intraday bars
    for days the daily feed is missing. Only completed sessions are used."""
    d = daily[["open", "high", "low", "close"]].copy()
    agg = intraday.groupby(intraday.index.normalize()).agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"))
    missing = agg[~agg.index.isin(d.index)]
    d = pd.concat([d, missing]).sort_index()
    return d[d.index.date <= last_complete_day]


def cpr_for_dates(sessions, dates):
    """CPR levels for each date, from the last completed session before it."""
    s = sessions.sort_index()
    pos = s.index.searchsorted(pd.DatetimeIndex(dates), side="left") - 1
    rows = []
    for p in pos:
        if p < 0:
            rows.append((np.nan,) * 5)
            continue
        h, l, c = s.high.iloc[p], s.low.iloc[p], s.close.iloc[p]
        P = (h + l + c) / 3
        bc = (h + l) / 2
        tc = 2 * P - bc
        rows.append((P, min(bc, tc), max(bc, tc), 2 * P - l, 2 * P - h))
    return pd.DataFrame(rows, index=pd.DatetimeIndex(dates), columns=["P", "BC", "TC", "R1", "S1"])


def bar_levels(intraday, sessions):
    days = intraday.index.normalize()
    lv = cpr_for_dates(sessions, days.unique())
    return lv.reindex(days).set_axis(intraday.index)


def daily_trend(daily, last_complete_day):
    d = daily[daily.index.date <= last_complete_day].copy()
    if len(d) < 50:
        return None
    d["ema20"] = d.close.ewm(span=20, adjust=False).mean()
    d["ema50"] = d.close.ewm(span=50, adjust=False).mean()
    return d.iloc[-1]


# --------------------------------------------------------------------- swings
def swing_points(x, k, kind):
    n = len(x)
    idx = []
    for i in range(k, n - k):
        w = x[i - k:i + k + 1]
        if (kind == "low" and x[i] == w.min()) or (kind == "high" and x[i] == w.max()):
            if not idx or i - idx[-1] > 1:          # skip flat duplicates
                idx.append(i)
    return idx


def _group(points, vals, other, p, kind, ok=lambda i: True):
    """Latest group of 2-3 equal swing points. `other` = highs (bottoms) or lows (tops).
    `ok(i)` = point i sits in the required CPR zone (others can't join the pattern)."""
    if not points or not ok(points[-1]):
        return None
    grp = [points[-1]]
    for t in reversed(points[:-1]):
        ref = np.mean(vals[grp])
        if grp[0] - t < p.min_gap:
            continue
        diff = (vals[t] - ref) / ref * 100
        if kind == "bottom" and diff < -p.tol:      # lower low -> pattern starts after it
            break
        if kind == "top" and diff > p.tol:          # higher high
            break
        if abs(diff) > p.tol or not ok(t):          # minor swing / wrong zone: ignore
            continue
        between = other[t:grp[0] + 1]
        if kind == "bottom":
            if between.max() < max(vals[t], vals[grp[0]]) * (1 + p.min_depth / 100):
                continue
        else:
            if between.min() > min(vals[t], vals[grp[0]]) * (1 - p.min_depth / 100):
                continue
        grp.insert(0, t)
        if len(grp) == 3:
            break
    return grp if len(grp) >= 2 else None


def detect(intraday, levels, p, kind):
    """Return pattern dict for the latest bars, or None."""
    df = intraday.iloc[-p.lookback:]
    lv = levels.iloc[-p.lookback:]
    h, l, c = df.high.to_numpy(), df.low.to_numpy(), df.close.to_numpy()
    n = len(df)
    if n < 2 * p.k + p.min_gap + 2:
        return None
    BC, TC, R1, S1 = (lv[c].to_numpy() for c in ("BC", "TC", "R1", "S1"))
    if kind == "bottom":
        def ok(i):
            return l[i] < BC[i] and abs(l[i] - S1[i]) / S1[i] * 100 <= p.lvl_tol
        pts = swing_points(l, p.k, "low")
        grp = _group(pts, l, h, p, "bottom", ok)
    else:
        def ok(i):
            return h[i] > TC[i] and h[i] <= R1[i] * (1 + p.lvl_tol / 100)
        pts = swing_points(h, p.k, "high")
        grp = _group(pts, h, l, p, "top", ok)
    if not grp or (n - 1 - grp[-1]) > p.recent:
        return None

    vals = l[grp] if kind == "bottom" else h[grp]
    for i, v in zip(grp, vals):
        row = lv.iloc[i]
        if row.isna().any():
            return None
        if kind == "bottom":
            if not (v < row.BC and abs(v - row.S1) / row.S1 * 100 <= p.lvl_tol):
                return None
        else:
            if not (v > row.TC and v <= row.R1 * (1 + p.lvl_tol / 100)):
                return None

    after = slice(grp[-1] + 1, n)
    if kind == "bottom":
        if (c[after] < vals.min() * (1 - p.tol / 100)).any():
            return None                                    # broke below the lows
        neck = h[grp[0]:grp[-1] + 1].max()
        crossed = np.flatnonzero(c[after] > neck)
        status = "BREAKOUT" if len(crossed) else "FORMING"
        sl = vals.min() * 0.999
    else:
        if (c[after] > vals.max() * (1 + p.tol / 100)).any():
            return None                                    # broke above the highs
        neck = l[grp[0]:grp[-1] + 1].min()
        crossed = np.flatnonzero(c[after] < neck)
        status = "BREAKDOWN" if len(crossed) else "FORMING"
        sl = vals.max() * 1.001

    cur = lv.iloc[-1]
    height = abs(neck - vals.mean())                     # measured move
    if kind == "bottom":
        cands = [cur.BC, cur.P, cur.TC, cur.R1, neck + height]
        tg = sorted(x for x in cands if x > neck * 1.001)[:2]
        if len(tg) < 2:
            tg.append(neck + 2 * height)
    else:
        cands = [cur.TC, cur.P, cur.BC, cur.S1, neck - height]
        tg = sorted((x for x in cands if x < neck * 0.999), reverse=True)[:2]
        if len(tg) < 2:
            tg.append(neck - 2 * height)
    name = ("Triple" if len(grp) == 3 else "Double") + (" bottom" if kind == "bottom" else " top")
    return {
        "pattern": name, "status": status,
        "points": [df.index[i] for i in grp], "level": float(vals.mean()),
        "neckline": float(neck), "sl": float(sl),
        "t1": float(tg[0]) if len(tg) > 0 else np.nan,
        "t2": float(tg[1]) if len(tg) > 1 else np.nan,
        "cross_time": df.index[grp[-1] + 1 + crossed[0]] if len(crossed) else None,
        "last": float(c[-1]), "S1": float(cur.S1), "R1": float(cur.R1),
        "BC": float(cur.BC), "TC": float(cur.TC), "P": float(cur.P),
    }


def scan(intraday_map, daily_map, interval, filter_name, last_complete_day,
         tol=None, lvl_tol=None, kinds=("bottom", "top")):
    p = PARAMS[interval]
    if tol is not None or lvl_tol is not None:
        p = Params(**{**p.__dict__, **({"tol": tol} if tol is not None else {}),
                      **({"lvl_tol": lvl_tol} if lvl_tol is not None else {})})
    filt = FILTERS[filter_name]
    rows, trend_ok = [], set()
    for sym, intra in intraday_map.items():
        daily = daily_map.get(sym)
        if daily is None:
            continue
        tr = daily_trend(daily, last_complete_day)
        if tr is None or not filt(tr):
            continue
        trend_ok.add(sym)
        sessions = session_ohlc(daily, intra, last_complete_day)
        lv = bar_levels(intra, sessions)
        for kind in kinds:
            r = detect(intra, lv, p, kind)
            if r:
                rows.append({"symbol": sym, **r, "daily_close": round(tr.close, 2),
                             "ema20": round(tr.ema20, 2), "ema50": round(tr.ema50, 2)})
    return pd.DataFrame(rows), trend_ok


# --------------------------------------------------------------------- chart
def chart(sym, intra, daily, last_complete_day, days=10, pat=None, height=480):
    if go is None:
        return None
    sessions = session_ohlc(daily, intra, last_complete_day)
    keep_days = intra.index.normalize().unique()[-days:]
    df = intra[intra.index.normalize().isin(keep_days)]
    lv = bar_levels(df, sessions)
    x = df.index.strftime("%d %b %H:%M")
    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=x, open=df.open, high=df.high, low=df.low, close=df.close,
                                 name=sym, increasing_line_color="#16a34a",
                                 decreasing_line_color="#dc2626", showlegend=False))
    # per-day level lines (break between days)
    day_id = df.index.normalize()
    brk = np.r_[False, day_id[1:] != day_id[:-1]]

    def stepped(series):
        y = series.to_numpy(dtype=float).copy()
        y[brk] = np.nan
        return y
    xs = np.asarray(x)
    for j, day in enumerate(day_id.unique()):          # one CPR band per day
        m = np.asarray(day_id == day)
        fig.add_trace(go.Scatter(x=xs[m], y=lv.TC[m], mode="lines", line=dict(width=0),
                                 showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=xs[m], y=lv.BC[m], mode="lines", line=dict(width=0),
                                 fill="tonexty", fillcolor="rgba(37,99,235,0.18)", name="CPR",
                                 legendgroup="cpr", showlegend=(j == 0), hoverinfo="skip"))
    for col, color, dash in (("P", "#2563eb", "dot"), ("R1", "#dc2626", "dash"),
                             ("S1", "#16a34a", "dash")):
        fig.add_trace(go.Scatter(x=x, y=stepped(lv[col]), mode="lines", name=col,
                                 line=dict(color=color, width=1.2, dash=dash)))
    if pat:
        bottom = "bottom" in pat["pattern"]
        shown = [p for p in pat["points"] if p in df.index]      # skip points outside view
        px = [p.strftime("%d %b %H:%M") for p in shown]
        ys = [df.low[p] if bottom else df.high[p] for p in shown]
        fig.add_trace(go.Scatter(x=px, y=ys, mode="markers+text", name=pat["pattern"],
                                 marker=dict(size=13, symbol="triangle-up" if bottom else "triangle-down",
                                             color="#7c3aed"),
                                 text=[f"{'B' if bottom else 'T'}{i + 1}" for i in range(len(px))],
                                 textposition="bottom center" if bottom else "top center"))
        start = px[0] if px else x[0]
        i0 = list(x).index(start)
        fig.add_trace(go.Scatter(x=list(x[i0:]), y=[pat["neckline"]] * (len(x) - i0), mode="lines",
                                 name="Neckline", line=dict(color="#f59e0b", width=1.6)))
    tick_idx = np.flatnonzero(np.r_[True, brk[1:]])
    step = 1 if len(tick_idx) <= 6 else 2
    tick_idx = tick_idx[::step]
    fig.update_xaxes(type="category", rangeslider_visible=False,
                     tickmode="array", tickvals=list(x[tick_idx]),
                     ticktext=[f"{df.index[i].day} {df.index[i]:%b}" for i in tick_idx],
                     tickangle=0, tickfont=dict(size=10))
    # y-range: candles + levels with padding, so markers are never clipped
    ys = np.r_[df.low.to_numpy(), df.high.to_numpy(),
               lv[["BC", "TC", "R1", "S1"]].to_numpy().ravel()]
    ys = ys[~np.isnan(ys)]
    lo, hi = ys.min(), ys.max()
    pad = (hi - lo) * 0.06
    fig.update_yaxes(range=[lo - pad, hi + pad], tickfont=dict(size=10))
    fig.update_layout(height=height, margin=dict(l=4, r=4, t=34, b=4),
                      title=dict(text=sym, x=0.01, font=dict(size=15)),
                      legend=dict(orientation="h", y=-0.08, x=0, yanchor="top", font=dict(size=10)),
                      hovermode="x unified")
    return fig
