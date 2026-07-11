"""CFB Spread Model -- matchup explorer + 2026 preseason schedule.
Historical numbers are out-of-sample (point-in-time features, walk-forward
predictions). 2026 shows a preseason talent prior only -- the full model
needs in-season data. Run:  python3 -m streamlit run app.py
"""
import pandas as pd
import streamlit as st

st.set_page_config(page_title="CFB Spread Model", layout="wide")


@st.cache_data
def load():
    games = pd.read_parquet("data/processed/demo_games.parquet")
    feats = pd.read_parquet("data/processed/team_features.parquet")
    try:
        logos = pd.read_parquet("data/processed/team_logos.parquet")
        logo_map = dict(zip(logos["team"], logos["logo"]))
    except FileNotFoundError:
        logo_map = {}
    try:
        sched = pd.read_parquet("data/processed/schedule_2026.parquet")
    except FileNotFoundError:
        sched = None
    return games, feats, logo_map, sched


games, feats, LOGOS, SCHED = load()
PIT_COLS = [c for c in feats.columns if c.endswith("_pit")]
NICE = {c: c.replace("_pit", "").replace("_", " ").title() for c in PIT_COLS}

st.title("College Football Spread Model")

modes = ["2023-25 by week", "2023-25 by team"]
if SCHED is not None:
    modes = ["2026 schedule"] + modes
mode = st.radio("Browse", modes, horizontal=True)


def logo_header(container, team_name, side_label):
    lc, nc = container.columns([1, 4])
    if team_name in LOGOS:
        lc.image(LOGOS[team_name], width=72)
    nc.subheader(team_name)
    nc.caption(side_label)


# ================= 2026 MODE =================
if mode == "2026 schedule":
    st.caption("2026 regular season, Weeks 4-13. The full model activates once "
               "Weeks 1-3 provide point-in-time data; until then the only honest "
               "signal is the preseason talent composite.")
    sub = st.radio("Pick by", ["Week", "Team"], horizontal=True, key="sub26")
    c1, c2 = st.columns(2)
    if sub == "Week":
        wk = c1.selectbox("Week", sorted(SCHED["week"].unique()))
        pool = SCHED[SCHED["week"] == wk].sort_values("home_team")
    else:
        teams = sorted(set(SCHED["home_team"]) | set(SCHED["away_team"]))
        team = c1.selectbox("Team", teams)
        pool = SCHED[(SCHED["home_team"] == team) |
                     (SCHED["away_team"] == team)].sort_values("week")
    if pool.empty:
        st.warning("No scheduled games for that selection.")
        st.stop()
    label = pool.apply(lambda r: f"Wk {r['week']}: {r['away_team']} @ {r['home_team']}",
                       axis=1)
    pick = c2.selectbox("Game", label)
    row = pool[label == pick].iloc[0]

    left, right = st.columns(2, gap="large")
    logo_header(left, row["home_team"], "HOME")
    logo_header(right, row["away_team"], "AWAY")
    if "talent_h" in row.index:
        left.metric("Talent composite (z)", f"{row['talent_h']:+.2f}",
                    delta=round(row["talent_h"] - row["talent_a"], 2))
        right.metric("Talent composite (z)", f"{row['talent_a']:+.2f}",
                     delta=round(row["talent_a"] - row["talent_h"], 2))
    st.divider()
    if "spread" in row.index and pd.notna(row["spread"]):
        fav = row["home_team"] if row["spread"] < 0 else row["away_team"]
        st.metric("Posted spread", f"{fav} {-abs(row['spread']):.1f}",
                  help=f"Current market number via {row['spread_provider']} (CFBD). "
                       "Early lines move a lot before kickoff.")
    if "prior_margin" in row.index:
        st.metric("Preseason prior: predicted home margin",
                  f"{row['prior_margin']:+.1f}",
                  help="Talent + home field only, trained on 2022-24. "
                       "NOT the full model.")
        st.info("This is a preseason prior, not a prediction against a line. "
                "In-season efficiency features -- and any market comparison -- "
                "begin Week 4 of 2026.")
    else:
        st.info("2026 talent composites aren't published yet -- schedule browsing "
                "only. The preseason prior appears automatically once 247Sports "
                "talent data lands (re-run the schedule cell in the eval notebook).")
    st.stop()

# ================= HISTORICAL MODES =================
st.caption("Walk-forward predictions vs the Bovada closing line, 2023-25. "
           "Team stats shown are what the model knew *entering* the game -- "
           "prior weeks only.")
c1, c2, c3 = st.columns(3)
season = c1.selectbox("Season", sorted(games["season"].unique(), reverse=True))
g_season = games[games["season"] == season]

if mode == "2023-25 by week":
    week = c2.selectbox("Week", sorted(g_season["week"].unique()))
    pool = g_season[g_season["week"] == week].sort_values("home_team")
    label = pool.apply(lambda r: f"{r['away_team']} @ {r['home_team']}", axis=1)
else:
    all_teams = sorted(set(g_season["home_team"]) | set(g_season["away_team"]))
    team = c2.selectbox("Team", all_teams)
    pool = g_season[(g_season["home_team"] == team) |
                    (g_season["away_team"] == team)].sort_values("week")
    label = pool.apply(lambda r: f"Wk {r['week']}: {r['away_team']} @ {r['home_team']}",
                       axis=1)

if pool.empty:
    st.warning("No games with a Bovada open+close for that selection.")
    st.stop()
pick = c3.selectbox("Game", label)
row = pool[label == pick].iloc[0]


def team_panel(col, team_name, opp_vals, side_label):
    with col:
        logo_header(st, team_name, side_label)
        tf = feats[(feats["season"] == row["season"]) &
                   (feats["week"] == row["week"]) &
                   (feats["team"] == team_name)]
        if tf.empty:
            st.warning("No point-in-time stats for this team-week.")
            return {}
        tf = tf.iloc[0]
        vals = {}
        for c in PIT_COLS:
            v = float(tf[c])
            vals[c] = v
            delta = None if opp_vals is None else round(v - opp_vals.get(c, 0), 3)
            st.metric(NICE[c], f"{v:.3f}", delta=delta,
                      help="Green/red arrow compares against the opponent.")
        return vals


left, right = st.columns(2, gap="large")
home_vals = team_panel(left, row["home_team"], None, "HOME")
away_vals = team_panel(right, row["away_team"], home_vals, "AWAY")

st.divider()
m1, m2, m3 = st.columns(3)
m1.metric("Model: predicted home margin", f"{row['model_margin']:+.1f}")
m2.metric("Bovada close (home spread)", f"{row['bov_close']:+.1f}",
          delta=f"opened {row['bov_open']:+.1f}")
m3.metric("Model's P(home covers)", f"{row['p_cover']:.0%}",
          help=f"Normal approximation, walk-forward sigma = {row['sigma']:.1f} points")

if abs(row["p_cover"] - 0.5) > 0.15:
    st.info("Caution: this is a high-confidence disagreement with the closing "
            "line -- the calibration analysis shows these invert (they hit ~44%, "
            "not 70%). Big model-vs-close gaps usually mean the model is missing "
            "something.")

with st.expander("Reveal the actual result"):
    margin = row["margin"]
    winner = row["home_team"] if margin > 0 else row["away_team"]
    covered = margin > -row["bov_close"]
    st.markdown(f"**Final: {winner} won by {abs(margin):.0f}.** "
                f"Home margin {margin:+.0f} vs close {row['bov_close']:+.1f} -> "
                f"home **{'covered' if covered else 'did not cover'}**.")
    st.markdown(f"Model error: {abs(margin - row['model_margin']):.1f} pts | "
                f"Market error: {abs(margin - (-row['bov_close'])):.1f} pts")
