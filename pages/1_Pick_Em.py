"""Play-money pick'em -- 2026 season. Lives in pages/ so Streamlit adds it as a page."""
import pandas as pd
import streamlit as st
from datetime import datetime, timezone
import pickslib as P

st.title("Pick'Em -- play money, real lines")
st.caption("Free game. Play-money balance only; nothing here involves real wagering. "
           "Lines are captured at the moment you pick and never change afterward. "
           f"{P.MIN_WEEKLY} picks to qualify each week, {P.MAX_WEEKLY} max.")

# ---------- schedule ----------
@st.cache_data(ttl=3600)
def load_sched():
    s = pd.read_parquet("data/app/schedule_2026.parquet")
    s["start_date"] = pd.to_datetime(s["start_date"], utc=True)
    return s

SCHED = load_sched()
SEASON = 2026

# ---------- auth ----------
if P.current_user() is None:
    tab_in, tab_up = st.tabs(["Sign in", "Create account"])
    with tab_in:
        e = st.text_input("Email", key="in_e")
        p = st.text_input("Password", type="password", key="in_p")
        if st.button("Sign in"):
            try:
                P.sign_in(e, p); st.rerun()
            except Exception as ex:
                st.error(f"Sign-in failed: {ex}")
    with tab_up:
        n = st.text_input("Display name", key="up_n")
        e2 = st.text_input("Email", key="up_e")
        p2 = st.text_input("Password (8+ characters)", type="password", key="up_p")
        if st.button("Create account"):
            try:
                P.sign_up(e2, p2, n); st.rerun()
            except Exception as ex:
                st.error(f"Sign-up failed: {ex}")
    st.stop()

prof = P.profile()
with st.sidebar:
    st.subheader(prof["display_name"])
    st.metric("Balance", f"{prof['balance']:,.0f}")
    if st.button("Sign out"):
        P.sign_out(); st.rerun()

# ---------- week + qualification status ----------
wk = st.selectbox("Week", sorted(SCHED["week"].unique()))
mine = P.week_picks(SEASON, wk)
n = len(mine)
if n < P.MIN_WEEKLY:
    st.warning(f"{n}/{P.MIN_WEEKLY} picks placed -- "
               f"{P.MIN_WEEKLY - n} more to qualify this week.")
elif n < P.MAX_WEEKLY:
    st.success(f"Qualified: {n} picks this week ({P.MAX_WEEKLY - n} remaining).")
else:
    st.info(f"Weekly limit reached ({P.MAX_WEEKLY} picks).")

# ---------- pickable games (not yet kicked off, has a market) ----------
now = datetime.now(timezone.utc)
pool = SCHED[(SCHED["week"] == wk) & (SCHED["start_date"] > now)]
pool = pool[pool["spread"].notna()].sort_values("start_date")

if pool.empty:
    st.info("No open games with posted lines for this week.")
else:
    label = pool.apply(lambda r: f"{r['away_team']} @ {r['home_team']}", axis=1)
    game = st.selectbox("Game", label)
    row = pool[label == game].iloc[0]

    fav = row["home_team"] if row["spread"] < 0 else row["away_team"]
    st.markdown(f"**Spread: {fav} {-abs(row['spread']):.1f}**  \u00b7  "
                f"kickoff {row['start_date']:%a %b %d, %H:%M} UTC")

    market = st.radio("Market", ["spread", "ml"], horizontal=True,
                      format_func=lambda m: "Against the spread (-110)" if m == "spread"
                      else "Moneyline (market odds)")
    if market == "ml" and (pd.isna(row.get("ml_home")) or pd.isna(row.get("ml_away"))):
        st.warning("No moneyline posted for this game yet -- spread only.")
        market = "spread"

    if market == "spread":
        opts = {f"{row['home_team']} {row['spread']:+.1f}": "home",
                f"{row['away_team']} {-row['spread']:+.1f}": "away"}
    else:
        opts = {f"{row['home_team']} {int(row['ml_home']):+d}": "home",
                f"{row['away_team']} {int(row['ml_away']):+d}": "away"}
    side = opts[st.radio("Your side", list(opts.keys()))]

    stake = st.number_input("Stake (play money)", min_value=10.0,
                            max_value=float(prof["balance"]), value=50.0, step=10.0)
    if st.button("Place pick"):
        try:
            P.place_pick(row, SEASON, wk, market, side, stake)
            st.success("Pick placed and locked in.")
            st.rerun()
        except Exception as ex:
            st.error(str(ex))

# ---------- my picks this week ----------
if mine:
    st.divider()
    st.subheader("My picks this week")
    dfm = pd.DataFrame(mine)
    show = dfm[["away_team", "home_team", "market", "side", "line",
                "odds", "stake", "status", "payout"]]
    st.dataframe(show, use_container_width=True, hide_index=True)
