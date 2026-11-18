"""
Stock screeners (Streamlit) - entry point
  Page 1: Momentum + EMA20 Retest (Nifty 500, daily)
  Page 2: F&O CPR Patterns (15-min / 1-hour double & triple bottoms/tops)

Run locally : python -m streamlit run app.py
Cloud       : Streamlit Community Cloud, main file = app.py
"""
import streamlit as st

st.set_page_config(page_title="Stock Screeners", page_icon="📈", layout="wide")
st.markdown("""<style>
.block-container{padding-top:1.2rem;padding-bottom:2rem}
@media (max-width:640px){.block-container{padding-left:.6rem;padding-right:.6rem}
 h1{font-size:1.4rem!important}}
</style>""", unsafe_allow_html=True)

pg = st.navigation([
    st.Page("momentum_page.py", title="Momentum Retest", icon="📈", default=True),
    st.Page("cpr_page.py", title="F&O CPR Patterns", icon="🎯"),
])
pg.run()
