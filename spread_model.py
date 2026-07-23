"""CFB Spread Model -- matchup explorer, 2026 schedule, and pick'em demo.
Historical numbers are out-of-sample (point-in-time features, walk-forward
predictions). 2026 shows posted market lines, fair-value moneylines derived
from them, and a preseason talent prior once published.
Run:  python3 -m streamlit run app.py
"""
from statistics import NormalDist

import pandas as pd
import streamlit as st

SIGMA = 16.2  # SD of realized margins around a prediction; stable 2023-25


@st.cache_data(ttl=3600)
def load():
    games = pd.read_parquet("data/app/demo_games.parquet")
    feats = pd.read_parquet("data/app/team_features.parquet")
    try:
        logos = pd.read_parquet("data/app/team_logos.parquet")
        logo_map = dict(zip(logos["team"], logos["logo"]))
    except FileNotFoundError:
        logo_map = {}
    try:
        sched = pd.read_parquet("data/app/schedule_2026.parquet")
    except FileNotFoundError:
        sched = None
    return games, feats, logo_map, sched


games, feats, LOGOS, SCHED = load()
PIT_COLS = [c for c in feats.columns if c.endswith("_pit")]
NICE = {c: c.replace("_pit", "").replace("_", " ").title() for c in PIT_COLS}

st.title("College Football Spread Model")

with st.expander("What do these stats mean?"):
    st.markdown(
        "**PPA (predicted points added)** -- average expected points a team adds "
        "per play, based on down, distance, and field position. The offensive "
        "version is what the offense creates; the defensive version is what the "
        "defense *allows*, so lower is better.\n\n"
        "**Success rate** -- share of plays that stay on schedule (roughly half "
        "the needed yards on 1st down, 70% on 2nd, all of it on 3rd/4th). "
        "Consistency, not size: how often you win a down.\n\n"
        "**Explosiveness** -- average PPA on *successful* plays only: chunk-play "
        "ability. High success + low explosiveness = methodical; the reverse = "
        "boom-or-bust. Defensive explosiveness is chunk plays allowed -- lower "
        "means when you lose a down, you lose it small.\n\n"
        "**Points for / against** -- plain scoring averages.\n\n"
        "**Rule of thumb:** every *Off* stat and Points For, higher is better; "
        "every *Def* stat and Points Against, lower is better. All numbers are "
        "*point-in-time* -- only what was knowable entering that game.")

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


def fav_spread_label(home, away, spread):
    """'Notre Dame -20.5' style, regardless of home/away."""
    fav = home if spread < 0 else away
    return f"{fav} {-abs(spread):.1f}"


def fair_ml(p):
    """Fair American odds from a win probability (no vig)."""
    if p > 0.5:
        return f"{-round(100 * p / (1 - p)):+d}"
    return f"+{round(100 * (1 - p) / p)}"


# ================= 2026 MODE =================
if mode == "2026 schedule":
    st.caption("2026 regular season, Weeks 1-16. Posted lines are current market "
               "numbers via CFBD and move before kickoff. The full model activates "
               "once Weeks 1-3 provide point-in-time data; until then the only "
               "honest signal is the preseason talent composite.")

    with st.sidebar:
        st.header("Your picks")
        if st.button("Clear all picks"):
            for k in [k for k in st.session_state if str(k).startswith("pick|")]:
                del st.session_state[k]
        label_map = st.session_state.setdefault("pick_labels", {})
        slip = []
        for k, v in st.session_state.items():
            if str(k).startswith("pick|") and isinstance(v, str) and v != "No pick":
                slip.append((label_map.get(k, ""), v))
        if slip:
            for game_lbl, choice in sorted(slip):
                st.markdown(f"**{choice}**  \n{game_lbl}")
            st.caption(f"{len(slip)} pick(s). Classic pick'em is 5 per week -- "
                       "picks live for this browser session (demo; no accounts yet).")
        else:
            st.caption("No picks yet. Choose a game and make your calls.")

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
    gid = str(row["game_id"])
    game_lbl = f"Wk {row['week']}: {row['away_team']} @ {row['home_team']}"

    left, right = st.columns(2, gap="large")
    logo_header(left, row["home_team"], "HOME")
    logo_header(right, row["away_team"], "AWAY")
    if "talent_h" in row.index and pd.notna(row.get("talent_h")):
        left.metric("Talent composite (z)", f"{row['talent_h']:+.2f}",
                    delta=round(row["talent_h"] - row["talent_a"], 2))
        right.metric("Talent composite (z)", f"{row['talent_a']:+.2f}",
                     delta=round(row["talent_a"] - row["talent_h"], 2))

    st.divider()

    def has(col):
        return col in row.index and pd.notna(row[col])

    any_market = False
    mcols = st.columns(3)

    if has("spread"):
        any_market = True
        with mcols[0]:
            st.markdown(f"**Spread: {fav_spread_label(row['home_team'], row['away_team'], row['spread'])}**")
            key = f"pick|{gid}|spread"
            st.radio("Who covers?",
                     ["No pick",
                      f"{row['home_team']} {row['spread']:+.1f}",
                      f"{row['away_team']} {-row['spread']:+.1f}"],
                     key=key)
            st.session_state["pick_labels"][key] = game_lbl
    if has("ml_home") and has("ml_away"):
        any_market = True
        with mcols[1]:
            st.markdown("**Moneyline (win outright)**")
            key = f"pick|{gid}|ml"
            st.radio("Who wins?",
                     ["No pick",
                      f"{row['home_team']} ML ({int(row['ml_home']):+d})",
                      f"{row['away_team']} ML ({int(row['ml_away']):+d})"],
                     key=key)
            st.session_state["pick_labels"][key] = game_lbl
    if has("total"):
        any_market = True
        with mcols[2]:
            st.markdown(f"**Total: {row['total']:.1f}**")
            key = f"pick|{gid}|total"
            st.radio("Over or under?",
                     ["No pick",
                      f"Over {row['total']:.1f}",
                      f"Under {row['total']:.1f}"],
                     key=key)
            st.session_state["pick_labels"][key] = game_lbl

    if any_market:
        st.caption(f"Lines via {row.get('spread_provider', 'CFBD')} (CFBD). "
                   "Early lines move a lot before kickoff.")
    else:
        st.info("No book has posted lines for this game yet -- markets appear "
                "here as they open.")

    # ---- moneylines: Ball Knowledge priced from our line when we have one,
    # otherwise fair value from the posted market spread ----
    ml_src = row["my_spread"] if has("my_spread") else (row["spread"] if has("spread") else None)
    if ml_src is not None:
        label = "Ball Knowledge moneyline" if has("my_spread") else "Fair moneyline (from market spread)"
        p_home = 1 - NormalDist().cdf(ml_src / SIGMA)
        st.divider()
        f1, f2 = st.columns(2)
        f1.metric(f"{label}: {row['home_team']}", fair_ml(p_home),
                  help=f"No-vig price implied by the "
                       f"{'Ball Knowledge' if has('my_spread') else 'market'} spread "
                       f"with a normal margin model (sigma = {SIGMA}).")
        f2.metric(f"{label}: {row['away_team']}", fair_ml(1 - p_home))
        if has("ml_home") and has("ml_away"):
            st.caption(f"Market moneylines for comparison: {row['home_team']} "
                       f"{int(row['ml_home']):+d} / {row['away_team']} "
                       f"{int(row['ml_away']):+d}. The gap is the book's vig "
                       f"plus any disagreement about the game.")

    if has("my_spread"):
        st.metric("Ball Knowledge Inc line",
                  fav_spread_label(row["home_team"], row["away_team"], row["my_spread"]),
                  delta=(f"{row['my_spread'] - row['spread']:+.1f} vs market"
                         if has("spread") else "no market line yet"),
                  help="Manually handicapped before kickoff; committed to git "
                       "for timestamping. Graded against closes and results "
                       "after each week.")

    if has("prior_margin"):
        st.metric("Preseason prior: predicted spread",
                  fav_spread_label(row["home_team"], row["away_team"], -row["prior_margin"]),
                  help="Talent + home field only, trained on 2022-25. "
                       "NOT the full model.")
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
            lower_is_better = c.startswith("def_") or "against" in c
            st.metric(NICE[c], f"{v:.3f}", delta=delta,
                      delta_color="inverse" if lower_is_better else "normal",
                      help="Arrow compares against the opponent. Green = the "
                           "better side of this stat, whichever direction that is.")
        return vals


left, right = st.columns(2, gap="large")
home_vals = team_panel(left, row["home_team"], None, "HOME")
away_vals = team_panel(right, row["away_team"], home_vals, "AWAY")

st.divider()
m1, m2, m3 = st.columns(3)
m1.metric("Model: predicted spread",
          fav_spread_label(row["home_team"], row["away_team"], -row["model_margin"]),
          help="The line the model would set. Compare directly with the Bovada close.")
m2.metric("Bovada close",
          fav_spread_label(row["home_team"], row["away_team"], row["bov_close"]),
          delta=f"opened {row['bov_open']:+.1f} (home)")
m3.metric("Model's P(home covers)", f"{row['p_cover']:.0%}",
          help=f"Normal approximation, walk-forward sigma = {row['sigma']:.1f} points")

if abs(row["p_cover"] - 0.5) > 0.15:
    st.info("Caution: this is a high-confidence disagreement with the closing "
            "line -- the calibration analysis (2023-25) shows these invert: the "
            "model's ~71% picks cover about 47% of the time. Big model-vs-close "
            "gaps usually mean the model is missing something.")

with st.expander("Reveal the actual result"):
    margin = row["margin"]
    winner = row["home_team"] if margin > 0 else row["away_team"]
    covered = margin > -row["bov_close"]
    close_label = fav_spread_label(row["home_team"], row["away_team"], row["bov_close"])
    cover_team = row["home_team"] if covered else row["away_team"]
    st.markdown(f"**Final: {winner} won by {abs(margin):.0f}.** "
                f"Against the close ({close_label}), "
                f"**{cover_team} covered**.")
    st.markdown(f"Model error: {abs(margin - row['model_margin']):.1f} pts | "
                f"Market error: {abs(margin - (-row['bov_close'])):.1f} pts")
