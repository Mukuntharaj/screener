# Momentum + EMA20 Retest Screener (Nifty 500)

Web app that lists the stocks meeting the strategy rules. It works in any
browser on a laptop or phone.

Files: `app.py` (the app) · `screener_core.py` (the rules) ·
`nifty500.csv` (fallback stock list) · `requirements.txt`

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
2. Upload the 4 files: `app.py`, `screener_core.py`, `nifty500.csv` and
   `requirements.txt`.
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
