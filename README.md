# Stock Screeners: Momentum Retest + F&O CPR Patterns

A web app with two pages (switch between them in the sidebar). It works in
any browser on a laptop or phone.

1. **📈 Momentum Retest**: Nifty 500, daily candles (20% week, then EMA20 retest).
2. **🎯 F&O CPR Patterns**: F&O stocks only, 15-min or 1-hour candles, with
   10–20-day candlestick charts. It lists:
   - **Double/triple bottoms below CPR at S1.** Trigger: a close above the
     neckline.
   - **Double/triple tops above CPR, below R1.** Trigger: a close below the
     neckline.

   Only stocks whose daily candle passes the EMA20/EMA50 filter are scanned.

| File | Purpose |
|---|---|
| `app.py` | Entry point and page menu |
| `momentum_page.py`, `screener_core.py` | Momentum screener |
| `cpr_page.py`, `cpr_core.py` | F&O CPR pattern screener and charts |
| `data_utils.py` | Yahoo/NSE data loading |
| `nifty500.csv`, `fo_stocks.csv` | Fallback stock lists |
| `requirements.txt` | Packages (now includes `plotly`) |

---

## Option A: run on your laptop

```
pip install -r requirements.txt
streamlit run app.py
```
The app opens at http://localhost:8501. The first load takes 30–60 seconds
while it downloads one year of prices for the Nifty 500 stocks.

**On your phone (same Wi-Fi):** Streamlit prints a "Network URL" such as
`http://192.168.1.5:8501`. Open that address on your phone. This works while
the laptop is on and the app is running.

## Option B: free cloud hosting (open from your phone anywhere)

1. Create a free GitHub account and make a new repository
   (for example `momentum-screener`). It can be private.
2. Upload **all 9 files** from the table above (same folder, no subfolders).
3. Go to https://share.streamlit.io, sign in with GitHub, and click
   **Create app**. Pick your repository, branch `main`, and file `app.py`.
   Click **Deploy**.
4. You get a link like `https://yourname-momentum-screener.streamlit.app`.
   Bookmark it, or use "Add to Home Screen" on your phone.

The free app goes to sleep after a few days without visits. Opening the link
wakes it up in about 1 minute.

---

## Daily routine
- **Evening (after about 4 PM):** open the app and tap **Refresh data**.
  - 🟢 **Buy-stop:** place a buy-stop just above *Buy above* with the
    stop-loss at *Stop loss*, using the *Qty* shown.
  - 📈 **Trades / Exit:** stocks marked **🚪 SELL at open** closed below
    EMA20, so sell them at the next day's open.
  - 👀 **Watchlist:** stocks waiting for a dip to EMA20.
- **During market hours:** keep "Use today's live candle" **off**. Signals
  are based on completed daily candles. The *Live* and *Triggered?* columns
  show today's price action.

## F&O CPR page: quick use
- In the sidebar, pick **15 min** or **1 hour**, the **daily trend filter**
  (default: close above both EMA20 and EMA50), and the pattern types.
- **Bottoms @ S1** and **Tops below R1** tabs: *Buy above* / *Sell below*
  is the neckline, with the SL and targets T1/T2 (the next CPR levels).
- **Charts** tab: 10–20 days of candles with each day's CPR band, P, R1 and
  S1, plus the pattern points and neckline. Use **Pattern zoom** on a phone.
- Detection settings can be adjusted under *Fine-tune detection*.
- The F&O list is fetched from NSE. If that fails, the app uses the bundled
  `fo_stocks.csv` (216 stocks, Nov 2026).

## Notes
- Prices come from Yahoo Finance (`SYMBOL.NS`), adjusted for splits and
  bonuses, and may be about 15 minutes delayed.
- The Nifty 500 list is fetched from niftyindices.com. If that fails, the
  app uses the bundled `nifty500.csv`; update that file every few months.
- The *In trade* tab shows the trades someone following the rules would be
  in. It doesn't know which ones you actually took.
- To test with your own data file instead of Yahoo, set the environment
  variable `SCREENER_CSV=path/to/nifty500_daily.csv`.
- This is a research tool, not investment advice.
