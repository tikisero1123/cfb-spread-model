"""Play-money pick'em -- 2026 season. Lives in pages/ so Streamlit adds it as a page."""
import pandas as pd
import streamlit as st
from datetime import datetime, timezone
import pickslib as P

st.title("Ball Knowledge Inc")
st.caption("Play money. Real lines.")

with st.expander("How it works"):
    st.markdown(
        "Two play-money wallets, \\$1,000\\$ each: the **Bovada book** uses "
        "market lines, the **Ball Knowledge book** uses our own. Bet spreads at "
        "-110 or moneylines at each book's price, \\$5\\$-\\$20\\$ a pick. "
        "Place at least 5 picks in a week to qualify, 10 max. Lines lock the "
        "moment you pick; you can cancel any pick for a full refund until its "
        "game kicks off. Wallets settle after each week's games -- the "
        "leaderboard ranks total bankroll.")
st.caption("Free game. Two play-money wallets -- $1,000$ each for the Bovada book and the Ball Knowledge book; nothing here involves real wagering. "
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
                result = P.sign_up(e2, p2, n)
                if result == "confirm":
                    st.success("Account created! Check your email for a "
                               "confirmation link, then come back and use "
                               "the Sign in tab.")
                else:
                    st.rerun()
            except Exception as ex:
                st.error(f"Sign-up failed: {ex}")
    st.stop()

prof = P.profile()
with st.sidebar:
    st.subheader(prof["display_name"])
    st.metric("Bovada wallet", f"${prof['balance_bov']:,.0f}$")
    st.metric("Ball Knowledge Inc wallet", f"${prof['balance_tiki']:,.0f}$")
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
    has_tiki = pd.notna(row.get("my_spread"))
    st.markdown(f"**Bovada spread: {fav} {-abs(row['spread']):.1f}**  \u00b7  "
                f"kickoff {row['start_date']:%a %b %d, %H:%M} UTC")
    if has_tiki:
        tfav = row["home_team"] if row["my_spread"] < 0 else row["away_team"]
        st.markdown(f"**Ball Knowledge spread: {tfav} {-abs(row['my_spread']):.1f}**")

    def _bov_ml_ok(r):
        h, a = r.get("ml_home"), r.get("ml_away")
        if pd.isna(h) or pd.isna(a):
            return False
        # junk sentinels (e.g. -100000) appear when books pull the ML on blowouts
        return abs(float(h)) <= 20000 and abs(float(a)) <= 20000

    market = st.radio("Market", ["spread", "ml"], horizontal=True,
                      format_func=lambda m: "Against the spread (-110)" if m == "spread"
                      else "Moneyline")
    bov_ml_ok = _bov_ml_ok(row)
    if market == "ml" and not bov_ml_ok and not has_tiki:
        st.warning("Moneyline is off the board for this game -- spread only.")
        market = "spread"

    book = "bovada"
    if has_tiki:
        if market == "ml" and not bov_ml_ok:
            st.info("Bovada's moneyline is off the board for this one -- Ball Knowledge book only.")
            book = "tiki"
        else:
            book = st.radio("Book (which line, which wallet)", ["bovada", "tiki"],
                            horizontal=True,
                            format_func=lambda b: "Bovada" if b == "bovada" else "Ball Knowledge book")
    line_used = row["my_spread"] if (market == "spread" and book == "tiki") else row["spread"]

    if market == "spread":
        opts = {f"{row['home_team']} {line_used:+.1f}": "home",
                f"{row['away_team']} {-line_used:+.1f}": "away"}
    elif book == "tiki":
        oh = P.tiki_ml_odds(row["my_spread"], "home")
        oa = P.tiki_ml_odds(row["my_spread"], "away")
        opts = {f"{row['home_team']} {oh:+d} (Ball Knowledge fair odds)": "home",
                f"{row['away_team']} {oa:+d} (Ball Knowledge fair odds)": "away"}
    else:
        opts = {f"{row['home_team']} {int(row['ml_home']):+d}": "home",
                f"{row['away_team']} {int(row['ml_away']):+d}": "away"}
    side = opts[st.radio("Your side", list(opts.keys()))]

    stake = st.number_input("Stake ($5$-$20$)", min_value=5.0,
                            max_value=20.0, value=10.0, step=1.0)

    # live odds + payout preview for the selected bet
    if market == "spread":
        odds_used = P.SPREAD_PRICE
    elif book == "tiki":
        odds_used = P.tiki_ml_odds(row["my_spread"], side)
    else:
        odds_used = int(row["ml_home"] if side == "home" else row["ml_away"])
    ret = P.american_payout(stake, odds_used)
    st.markdown(f"**Odds: {odds_used:+d}**  \u00b7  risk \\${stake:,.0f}\\$ "
                f"to win \\${ret - stake:,.2f}\\$ \u00b7 returns \\${ret:,.2f}\\$ if it hits")

    if st.button("Place pick"):
        try:
            P.place_pick(row, SEASON, wk, market, side, stake, book)
            st.success("Pick placed and locked in.")
            st.rerun()
        except Exception as ex:
            st.error(str(ex))

# ---------- my picks this week ----------
if mine:
    st.divider()
    st.subheader("My picks this week")
    dfm = pd.DataFrame(mine)
    icon = {"open": "\u23f3", "won": "\u2705", "lost": "\u274c", "push": "\u2796"}
    rows = []
    for _, r in dfm.iterrows():
        team = r["home_team"] if r["side"] == "home" else r["away_team"]
        if r["market"] == "spread":
            ln = float(r["line"]) if r["side"] == "home" else -float(r["line"])
            bet = f"{team} {ln:+.1f}"
        else:
            bet = f"{team} ML"
        ret = P.american_payout(float(r["stake"]), int(r["odds"]))
        paid = float(r.get("payout") or 0)
        rows.append({
            "Matchup": f"{r['away_team']} @ {r['home_team']}",
            "Bet": bet,
            "Book": "Ball Knowledge" if r["book"] == "tiki" else "Bovada",
            "Odds": f"{int(r['odds']):+d}",
            "Stake": f"${float(r['stake']):,.0f}$",
            "Returns": f"${ret:,.2f}$" if r["status"] == "open" else f"${paid:,.2f}$",
            "Result": icon.get(r["status"], "?"),
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # cancel open picks before kickoff (refunds the stake)
    kick = dict(zip(SCHED["game_id"].astype(str), SCHED["start_date"]))
    cancellable = [r for r in mine if r["status"] == "open"
                   and (kick.get(str(r["game_id"])) is None
                        or kick[str(r["game_id"])] > now)]
    if cancellable:
        def _desc(r):
            team = r["home_team"] if r["side"] == "home" else r["away_team"]
            kind = "ML" if r["market"] == "ml" else "spread"
            bk = "BK" if r["book"] == "tiki" else "Bov"
            return f"{team} {kind} ({bk}, ${float(r['stake']):,.0f}$)"
        c1, c2 = st.columns([3, 1])
        labels = {_desc(r): r for r in cancellable}
        choice = c1.selectbox("Cancel a pick (refunds the stake, only before kickoff)",
                              list(labels.keys()))
        c2.markdown("<div style='height:1.75em'></div>", unsafe_allow_html=True)
        if c2.button("Cancel pick"):
            try:
                P.cancel_pick(labels[choice])
                st.success("Pick canceled, stake refunded.")
                st.rerun()
            except Exception as ex:
                st.error(str(ex))
