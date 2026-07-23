"""Ball Knowledge leaderboard -- public standings by total bankroll."""
import pandas as pd
import streamlit as st
import pickslib as P

st.title("Leaderboard")
st.caption("Ranked by total bankroll across both books. Everyone starts with "
           "\\$2,000\\$ total. Standings move when a week's games settle.")

rows = P.sb().table("profiles").select(
    "display_name, balance_bov, balance_tiki").execute().data

if not rows:
    st.info("No players yet.")
    st.stop()

df = pd.DataFrame(rows)
df["total"] = df["balance_bov"] + df["balance_tiki"]
df = df.sort_values("total", ascending=False).reset_index(drop=True)

medals = {0: "\U0001F947", 1: "\U0001F948", 2: "\U0001F949"}
board = pd.DataFrame({
    "Rank": [medals.get(i, str(i + 1)) for i in df.index],
    "Player": df["display_name"],
    "Ball Knowledge wallet": df["balance_tiki"].map(lambda v: f"${v:,.0f}$"),
    "Bovada wallet": df["balance_bov"].map(lambda v: f"${v:,.0f}$"),
    "Total": df["total"].map(lambda v: f"${v:,.0f}$"),
})
st.dataframe(board, use_container_width=True, hide_index=True)

up = (df["total"] > 2000).sum()
down = (df["total"] < 2000).sum()
st.caption(f"{len(df)} players \u00b7 {up} up on the books \u00b7 {down} down")
