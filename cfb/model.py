"""
The model and the backtest. This is where the project stops being a pipeline and
becomes a betting model.

Two honest rules baked in:

1. WALK-FORWARD ONLY. To predict a season, train only on EARLIER seasons. Never
   let the model see the year it is being graded on. This mirrors real life: in
   2023 you did not have 2024 games.

2. THE SPREAD IS THE BAR. The headline number is not "did we pick winners." It
   is model error vs the market's error at predicting margin. The market is very
   good, so beating it is hard and that is the point. We report both side by side
   so there is nowhere to hide.

A note on CLV: true closing line value needs the OPENING and CLOSING line for
each game stored separately. Right now we pull one consensus spread per game, so
this backtest grades against that single line as a stand-in. Capturing open vs
close is the upgrade that makes CLV real. Until then, read these results as
directional, not proof.
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from sklearn.linear_model import RidgeCV
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline

from cfb.features import FEATURE_COLS

BREAK_EVEN = 0.5238  # win rate needed to profit at -110 odds


def walk_forward_backtest(model_table: pd.DataFrame,
                          feature_cols: list[str] = FEATURE_COLS,
                          min_train_rows: int = 200) -> pd.DataFrame:
    """For each season, train on all prior seasons and predict this one. Returns
    the test rows with a model_margin column added."""
    # Guard: a few rows can carry inf/NaN features (teams with almost no prior
    # games, odd stat values). They blow up the linear algebra and pollute the
    # result, so drop them up front and say how many.
    mt = model_table.replace([np.inf, -np.inf], np.nan)
    n_before = len(mt)
    mt = mt.dropna(subset=feature_cols + ["margin"]).reset_index(drop=True)
    if len(mt) < n_before:
        print(f"  dropped {n_before - len(mt)} rows with missing or infinite features")
    model_table = mt

    seasons = sorted(model_table["season"].unique())
    out = []
    for test_season in seasons:
        train = model_table[model_table["season"] < test_season]
        test = model_table[model_table["season"] == test_season]
        if len(train) < min_train_rows:
            print(f"  {test_season}: skipped (only {len(train)} prior rows to train on)")
            continue
        model = make_pipeline(
            StandardScaler(),
            RidgeCV(alphas=[0.1, 1.0, 10.0, 100.0]),
        )
        model.fit(train[feature_cols], train["margin"])
        test = test.copy()
        test["model_margin"] = model.predict(test[feature_cols])
        out.append(test)
        print(f"  {test_season}: trained on {len(train)} games, predicted {len(test)}")
    if not out:
        raise RuntimeError("No season had enough history to backtest. Pull more years.")
    return pd.concat(out, ignore_index=True)


def grade(preds: pd.DataFrame) -> None:
    """Print the two things that matter: accuracy vs the spread, and what betting
    the model's edges would have done."""
    g = preds.dropna(subset=["spread_home"]).copy()
    if g.empty:
        print("No games with a spread to grade against.")
        return

    # Market's own margin prediction is the negative of the home spread.
    g["market_margin"] = -g["spread_home"]
    model_mae = (g["model_margin"] - g["margin"]).abs().mean()
    spread_mae = (g["market_margin"] - g["margin"]).abs().mean()

    print("\n=== Accuracy at predicting actual margin (lower is better) ===")
    print(f"  Model  MAE: {model_mae:5.2f} points")
    print(f"  Vegas  MAE: {spread_mae:5.2f} points   <- the bar")
    verdict = "BEATS" if model_mae < spread_mae else "does NOT beat"
    print(f"  Model {verdict} the spread on margin error "
          f"({model_mae - spread_mae:+.2f}).")

    # Edge = how much more the model likes the home side than the market does.
    g["edge"] = g["model_margin"] - g["market_margin"]
    # Home covers when actual margin beats the spread line.
    g["home_covered"] = g["margin"] + g["spread_home"] > 0
    g["push"] = (g["margin"] + g["spread_home"]) == 0

    print("\n=== If you bet every game the model disagreed with by >= threshold ===")
    print("  thr   bets    win%   ROI/bet   (break-even win% = 52.4)")
    for thr in [0.0, 1.0, 2.0, 3.0, 4.0, 6.0]:
        bets = g[(g["edge"].abs() >= thr) & (~g["push"])].copy()
        if bets.empty:
            print(f"  {thr:>3.0f}    {0:>4}     --       --")
            continue
        # Bet home when edge positive, away when negative.
        bet_home = bets["edge"] > 0
        won = np.where(bet_home, bets["home_covered"], ~bets["home_covered"])
        win_rate = won.mean()
        roi = np.where(won, 100 / 110, -1.0).mean()
        print(f"  {thr:>3.0f}   {len(bets):>4}    {win_rate*100:5.1f}    {roi:+6.3f}")

    print("\nReading it: if win% sits around 50 and ROI is negative, the model is "
          "not beating the market yet. That is the normal, honest starting point. "
          "Real edges are small and survive only at higher thresholds, if at all.")


from sklearn.linear_model import Ridge, LinearRegression
import pandas as pd


def backtest_ridge(table, feature_cols, alpha=1.0, min_train=300, verbose=True):
    """Walk-forward backtest by season using Ridge regression."""
    out = []
    for season in sorted(table["season"].unique()):
        train = table[table["season"] < season].dropna(subset=list(feature_cols) + ["margin"])
        test = table[table["season"] == season].dropna(subset=list(feature_cols) + ["margin"])
        if len(train) < min_train:
            if verbose:
                print(f"  {season}: skipped ({len(train)} prior rows)")
            continue
        m = Ridge(alpha=alpha).fit(train[feature_cols], train["margin"])
        t = test.copy()
        t["model_margin"] = m.predict(t[feature_cols])
        out.append(t)
        if verbose:
            print(f"  {season}: trained {len(train)}, predicted {len(t)}")
    return pd.concat(out, ignore_index=True)


def predict_spread(home_team, away_team, season, week, table, feature_cols):
    """Predict one matchup, trained only on games strictly before (season, week)."""
    hist = table[(table["season"] < season) |
                 ((table["season"] == season) & (table["week"] < week))]
    train = hist.dropna(subset=list(feature_cols) + ["margin"])
    m = Ridge(alpha=1.0).fit(train[feature_cols], train["margin"])
    row = table[(table["season"] == season) & (table["week"] == week) &
                (table["home_team"] == home_team) & (table["away_team"] == away_team)]
    if row.empty:
        raise ValueError(f"Game not found: {home_team} vs {away_team}, season {season} week {week}")
    pred = float(m.predict(row[feature_cols])[0])
    print(f"{home_team} vs {away_team} ({season} wk {week}): predicted home margin {pred:+.1f}")
    return pred


def find_games(team, season, table):
    """List a team's games in a season."""
    hits = table[(table["season"] == season) &
                 ((table["home_team"] == team) | (table["away_team"] == team))]
    return hits[["week", "home_team", "away_team", "spread_home", "margin"]].sort_values("week")


from sklearn.linear_model import Ridge, LinearRegression
import pandas as pd


def backtest_ridge(table, feature_cols, alpha=1.0, min_train=300, verbose=True):
    """Walk-forward backtest by season using Ridge regression."""
    out = []
    for season in sorted(table["season"].unique()):
        train = table[table["season"] < season].dropna(subset=list(feature_cols) + ["margin"])
        test = table[table["season"] == season].dropna(subset=list(feature_cols) + ["margin"])
        if len(train) < min_train:
            if verbose:
                print(f"  {season}: skipped ({len(train)} prior rows)")
            continue
        m = Ridge(alpha=alpha).fit(train[feature_cols], train["margin"])
        t = test.copy()
        t["model_margin"] = m.predict(t[feature_cols])
        out.append(t)
        if verbose:
            print(f"  {season}: trained {len(train)}, predicted {len(t)}")
    return pd.concat(out, ignore_index=True)


def predict_spread(home_team, away_team, season, week, table, feature_cols):
    """Predict one matchup, trained only on games strictly before (season, week)."""
    hist = table[(table["season"] < season) |
                 ((table["season"] == season) & (table["week"] < week))]
    train = hist.dropna(subset=list(feature_cols) + ["margin"])
    m = Ridge(alpha=1.0).fit(train[feature_cols], train["margin"])
    row = table[(table["season"] == season) & (table["week"] == week) &
                (table["home_team"] == home_team) & (table["away_team"] == away_team)]
    if row.empty:
        raise ValueError(f"Game not found: {home_team} vs {away_team}, season {season} week {week}")
    pred = float(m.predict(row[feature_cols])[0])
    print(f"{home_team} vs {away_team} ({season} wk {week}): predicted home margin {pred:+.1f}")
    return pred


def find_games(team, season, table):
    """List a team's games in a season."""
    hits = table[(table["season"] == season) &
                 ((table["home_team"] == team) | (table["away_team"] == team))]
    return hits[["week", "home_team", "away_team", "spread_home", "margin"]].sort_values("week")
