"""Ball Knowledge -- entrypoint router. Pages live in their own modules."""
import streamlit as st

st.set_page_config(page_title="Ball Knowledge", layout="wide")
try:
    st.logo("assets/bk_logo.png")
except Exception:
    pass

pg = st.navigation([
    st.Page("spread_model.py", title="Spread Model", icon="📊", default=True),
    st.Page("pickem_page.py", title="Pick'Em", icon="🏈"),
    st.Page("leaderboard_page.py", title="Leaderboard", icon="🏆"),
])
pg.run()
