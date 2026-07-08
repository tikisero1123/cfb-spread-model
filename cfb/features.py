"""
Point-in-time feature engine.

The single rule this file exists to enforce:
a feature for a given game uses ONLY information available BEFORE kickoff.

Every team-efficiency feature is an expanding mean of that team's PRIOR games
in the same season, shrunk toward a fixed league baseline so that early-season
samples (Week 4 has only 3 prior games) don't get trusted too much.

If this rule breaks, the backtest looks great and means nothing. So the leakage
test in tests/test_no_leakage.py corrupts future games and asserts that earlier
features do not move. Run it before you ever trust a result.
"""

from __future__ import annotations
import pandas as pd
import numpy as np

# Per-team-per-game stats we roll forward. Pulled from CFBD /stats/game/advanced
# plus the box score. def_* are what the opponent did against this team.
EFFICIENCY_COLS = [
    "off_ppa",
    "def_ppa",
    "off_success_rate",
    "def_success_rate",
    "off_explosiveness",
    "def_explosiveness",
    "points_for",
    "points_against",
]

# Fixed league baselines used as the shrinkage prior. These are constants on
# purpose: a constant prior cannot leak. They are rough CFB averages and are
# tunable, but do not derive them from the same-season data you are predicting.
DEFAULT_PRIOR = {
    "off_ppa": 0.0,
    "def_ppa": 0.0,
    "off_success_rate": 0.43,
    "def_success_rate": 0.43,
    "off_explosiveness": 1.6,
    "def_explosiveness": 1.6,
    "points_for": 28.0,
    "points_against": 28.0,
}


def point_in_time_team_features(
    team_games: pd.DataFrame,
    shrink_k: float = 4.0,
    prior: dict | None = None,
) -> pd.DataFrame:
    """
    Build leak-free, shrunk rolling means for every team-game.

    team_games: one row per team per game. Required columns:
        game_id, season, week, team, and every name in EFFICIENCY_COLS.

    shrink_k: pseudo-count for shrinkage. With k=4, a team gets pulled halfway
        to the league baseline after 4 prior games. Bigger k = more skeptical
        of small samples.

    Returns the input rows plus one "<col>_pit" column per efficiency stat and
    an "n_prior" column (how many prior games fed the estimate).

    Estimate for a row =
        (n_prior * mean_of_prior_games + k * league_prior) / (n_prior + k)
    For a team's first game n_prior = 0, so the estimate is exactly the prior.
    """
    prior = {**DEFAULT_PRIOR, **(prior or {})}

    df = team_games.sort_values(["season", "team", "week", "game_id"]).copy()
    grp = df.groupby(["season", "team"], sort=False)

    # Number of games strictly before this one, within season. cumcount is 0 for
    # the first game, which is exactly the count of prior games.
    df["n_prior"] = grp.cumcount()

    for col in EFFICIENCY_COLS:
        if col not in df.columns:
            raise KeyError(f"team_games is missing required column: {col}")
        # shift(1) drops the current game; expanding().mean() averages only the
        # games before it. This is the line that makes the feature honest.
        prior_mean = grp[col].transform(lambda s: s.shift(1).expanding().mean())
        n = df["n_prior"].to_numpy(dtype=float)
        pm = prior_mean.fillna(0.0).to_numpy(dtype=float)  # NaN only where n==0
        df[f"{col}_pit"] = (n * pm + shrink_k * prior[col]) / (n + shrink_k)

    return df


def build_model_table(
    team_features: pd.DataFrame,
    games: pd.DataFrame,
    min_week: int = 4,
) -> pd.DataFrame:
    """
    Turn per-team point-in-time features into one row per game, from the home
    team's perspective, with the target margin and the market spread attached.

    games: one row per game. Required columns:
        game_id, season, week, home_team, away_team, neutral_site,
        home_points, away_points, spread_home
        (spread_home is the market line from the home side: -6.5 = home favored
         by 6.5. Margin and spread share a sign convention so edge = clean diff.)

    team_features: output of point_in_time_team_features().

    Returns model-ready rows with feature diffs, the target margin, the spread,
    and the implied edge column you'll grade in the backtest.
    """
    pit_cols = [f"{c}_pit" for c in EFFICIENCY_COLS]
    keep = ["game_id", "team", "n_prior"] + pit_cols
    tf = team_features[keep]

    home = tf.add_prefix("home_").rename(columns={"home_game_id": "game_id", "home_team": "home_team"})
    away = tf.add_prefix("away_").rename(columns={"away_game_id": "game_id", "away_team": "away_team"})

    g = games.copy()
    g = g.merge(home, left_on=["game_id", "home_team"], right_on=["game_id", "home_team"], how="inner")
    g = g.merge(away, left_on=["game_id", "away_team"], right_on=["game_id", "away_team"], how="inner")

    # Target: actual margin from the home side.
    g["margin"] = g["home_points"] - g["away_points"]

    # Matchup differentials. Let the model learn the signs; keep these intuitive.
    g["off_ppa_diff"] = g["home_off_ppa_pit"] - g["away_off_ppa_pit"]
    g["def_ppa_diff"] = g["home_def_ppa_pit"] - g["away_def_ppa_pit"]
    g["success_rate_diff"] = g["home_off_success_rate_pit"] - g["away_off_success_rate_pit"]
    g["explosiveness_diff"] = g["home_off_explosiveness_pit"] - g["away_off_explosiveness_pit"]
    # Each team's average scoring margin so far, then the difference of those.
    home_pm = g["home_points_for_pit"] - g["home_points_against_pit"]
    away_pm = g["away_points_for_pit"] - g["away_points_against_pit"]
    g["scoring_margin_diff"] = home_pm - away_pm
    # Home field, off when the game is at a neutral site.
    g["home_field"] = (~g["neutral_site"].astype(bool)).astype(int)

    # Market benchmark and the edge you'll actually grade.
    # model_margin gets filled in by the modeling step; edge = model - (-spread).
    g["spread_home"] = g["spread_home"]

    feature_cols = [
        "off_ppa_diff",
        "def_ppa_diff",
        "success_rate_diff",
        "explosiveness_diff",
        "scoring_margin_diff",
        "home_field",
    ]
    id_cols = [
        "game_id", "season", "week", "home_team", "away_team",
        "neutral_site", "home_points", "away_points",
        "home_n_prior", "away_n_prior",
    ]
    out = g[id_cols + feature_cols + ["spread_home", "margin"]].copy()

    # Week 4+ only, per the project spec. Early-season noise stays out of v1.
    out = out[out["week"] >= min_week].reset_index(drop=True)
    return out


FEATURE_COLS = [
    "off_ppa_diff",
    "def_ppa_diff",
    "success_rate_diff",
    "explosiveness_diff",
    "scoring_margin_diff",
    "home_field",
]


def attach_diffs(model_table, team_df, cols):
    """Merge per-team columns onto the game table as home-minus-away diffs.
    Dedupes after merging: teams with two games in one season-week fan out."""
    mt = model_table.copy()
    for side, key in [("_h", "home_team"), ("_a", "away_team")]:
        sub = team_df[["season", "week", "team"] + cols].rename(
            columns={c: c + side for c in cols})
        mt = mt.merge(sub, left_on=["season", "week", key],
                      right_on=["season", "week", "team"], how="left").drop(columns="team")
    for c in cols:
        mt[c + "_diff2"] = mt[c + "_h"] - mt[c + "_a"]
        mt = mt.drop(columns=[c + "_h", c + "_a"])
    mt = mt.drop_duplicates(subset=["season", "week", "home_team", "away_team"]).reset_index(drop=True)
    return mt


def add_talent_diff(model_table, talent):
    """Merge season talent z-scores as a home-minus-away diff. Missing (FCS)
    teams get the season minimum."""
    mt = model_table.copy()
    for side, key in [("_h", "home_team"), ("_a", "away_team")]:
        sub = talent[["season", "team", "talent_z"]].rename(columns={"talent_z": "talent" + side})
        mt = mt.merge(sub, left_on=["season", key], right_on=["season", "team"],
                      how="left").drop(columns="team")
    season_min = talent.groupby("season")["talent_z"].min()
    for c in ["talent_h", "talent_a"]:
        mt[c] = mt[c].fillna(mt["season"].map(season_min))
    mt["talent_diff"] = mt["talent_h"] - mt["talent_a"]
    return mt.drop(columns=["talent_h", "talent_a"])
