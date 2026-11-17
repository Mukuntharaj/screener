"""
Core logic for the Momentum + EMA20-retest screener.
Same rules as the backtest (momentum_pullback_backtest.py, setup R20, exit TRAIL).

Rules
  Event   : close >= 20 % above the close 5 trading days earlier,
            no single day > 50 % of that move, close > EMA20 > EMA50.
  Watch   : 20 trading days after the event; cancelled on a close below EMA50.
  Setup   : candle with low <= EMA20 and close > EMA20  (retest that holds).
  Entry   : buy-stop above the setup high, valid for the next 3 trading days.
  SL      : setup-candle low.
  Exit    : next open after a close below EMA20, or SL, or 40 trading days.
  Size    : qty = (capital x risk %) / (entry - SL)
"""
import numpy as np
import pandas as pd

MOVE, DAYS, MAX_SHARE = 0.20, 5, 0.5
WATCH, TRIGGER_DAYS, MAX_HOLD = 20, 3, 40


def add_indicators(df):
    """df: one stock, columns open/high/low/close, DatetimeIndex ascending."""
    df = df.copy()
    df["ema20"] = df.close.ewm(span=20, adjust=False, min_periods=20).mean()
    df["ema50"] = df.close.ewm(span=50, adjust=False, min_periods=50).mean()
    ret1 = df.close.pct_change()
    df["week_ret"] = df.close / df.close.shift(DAYS) - 1
    df["max_day"] = ret1.rolling(DAYS, min_periods=DAYS).max()
    df["event"] = ((df.week_ret >= MOVE) & (df.max_day <= MAX_SHARE * df.week_ret)
                   & (df.close > df.ema20) & (df.ema20 > df.ema50))
    return df


def scan_stock(sym, df, capital=100000, risk_pct=1.0):
    """
    Walk the stock's history like the backtest and return its CURRENT state
    (dict) or None if it is not on the radar. The last row of df is treated as
    the latest completed candle.
    """
    if len(df) < 60:
        return None
    df = add_indicators(df)
    o, h, l, c = (df[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    e20, e50, ev = df.ema20.to_numpy(), df.ema50.to_numpy(), df.event.to_numpy()
    dates = df.index
    n, last = len(df), len(df) - 1

    # only events recent enough to still matter
    start = max(0, n - (WATCH + TRIGGER_DAYS + MAX_HOLD + 5))
    idx = [i for i in np.flatnonzero(ev) if i >= start]
    episodes = [e for j, e in enumerate(idx) if j == 0 or e - idx[j - 1] > DAYS]

    state = None
    busy_until = -1
    for i in episodes:
        if i <= busy_until:
            continue
        st = {"symbol": sym, "event_date": dates[i].date(),
              "week_move_%": round(df.week_ret.iloc[i] * 100, 1)}
        k = i + 1
        result = None
        while k <= min(i + WATCH, last):
            if c[k] < e50[k]:
                result = ("CANCELLED", k)
                break
            if l[k] <= e20[k] < c[k]:                       # setup candle
                trig, sl = h[k], l[k]
                entry_k = None
                for m in range(k + 1, min(k + 1 + TRIGGER_DAYS, n)):
                    if h[m] > trig:
                        entry_k = m
                        break
                if entry_k is None:
                    if k + TRIGGER_DAYS >= last + 1:          # trigger still valid
                        result = ("BUY-STOP", k, trig, sl, k + TRIGGER_DAYS - last)
                        break
                    k += 1
                    continue
                entry = max(o[entry_k], trig)
                # follow the trade
                status, exit_k = "IN TRADE", None
                for m in range(entry_k, min(entry_k + MAX_HOLD, n)):
                    if m > entry_k and o[m] <= sl:
                        status, exit_k = "STOPPED", m
                        break
                    if l[m] <= sl:
                        status, exit_k = "STOPPED", m
                        break
                    if c[m] < e20[m]:
                        if m == last:
                            status = "EXIT AT NEXT OPEN"
                        else:
                            status, exit_k = "CLOSED (EMA20)", m + 1
                        break
                else:
                    if entry_k + MAX_HOLD - 1 <= last:
                        status, exit_k = "CLOSED (40 days)", entry_k + MAX_HOLD - 1
                result = ("TRADE", k, trig, sl, entry_k, entry, status, exit_k)
                break
            k += 1
        if result is None:
            if i + WATCH > last:
                result = ("WATCH",)
            else:
                result = ("EXPIRED",)

        kind = result[0]
        if kind == "WATCH":
            st.update(status="WATCHLIST", days_left=i + WATCH - last,
                      dist_to_ema20_pct=round((c[last] / e20[last] - 1) * 100, 1))
            state = st
        elif kind == "BUY-STOP":
            _, k, trig, sl, left = result
            risk = trig - sl
            qty = int(capital * risk_pct / 100 // risk) if risk > 0 else 0
            st.update(status="BUY-STOP ACTIVE", setup_date=dates[k].date(),
                      buy_above=round(trig, 2), stop_loss=round(sl, 2),
                      risk_pct=round(risk / trig * 100, 2), qty=qty,
                      position_value=round(qty * trig), valid_days_left=left)
            state = st
        elif kind == "TRADE":
            _, k, trig, sl, ek, entry, status, xk = result
            st.update(status=status, setup_date=dates[k].date(), entry_date=dates[ek].date(),
                      entry=round(entry, 2), stop_loss=round(sl, 2),
                      ltp=round(c[last], 2), ema20=round(e20[last], 2),
                      pnl_pct=round((c[last] / entry - 1) * 100, 2),
                      days_held=last - ek + 1)
            busy_until = xk if xk is not None else last   # open trade blocks new events
            if xk is not None:
                st["exit_date"] = dates[min(xk, last)].date()
            state = st if status in ("IN TRADE", "EXIT AT NEXT OPEN") or (
                xk is not None and xk >= last - 2) else state
        # CANCELLED / EXPIRED: nothing to show unless a later episode exists

    if state is not None:
        state["new_event_today"] = bool(ev[last])
        state["close"] = round(c[last], 2)
        state["last_date"] = dates[last].date()
    return state


def scan_universe(prices, capital=100000, risk_pct=1.0):
    """prices: dict symbol -> OHLC DataFrame. Returns DataFrame of states."""
    rows = []
    for sym, df in prices.items():
        try:
            s = scan_stock(sym, df, capital, risk_pct)
        except Exception:                       # bad data for one stock
            s = None
        if s:
            rows.append(s)
    return pd.DataFrame(rows)
