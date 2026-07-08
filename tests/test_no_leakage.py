"""
The test that decides whether this whole project is trustworthy.

Two checks:

1. NO FUTURE LEAK. Corrupt every game from week W onward, rebuild features, and
   assert that every feature for games BEFORE week W is byte-for-byte identical.
   If a future game can change a past feature, the model is cheating.

2. FIRST GAME == PRIOR. A team's first game of the season has zero prior games,
   so its point-in-time estimate must equal the fixed league prior exactly.

Run:  python tests/test_no_leakage.py
"""

from __future__ import annotations
import sys, os
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cfb.features import (
    point_in_time_team_features,
    EFFICIENCY_COLS,
    DEFAULT_PRIOR,
)
from tests.make_synthetic import make_synthetic

PIT_COLS = [f"{c}_pit" for c in EFFICIENCY_COLS]


def test_no_future_leak(corrupt_from_week=7):
    team_games, _ = make_synthetic()

    clean = point_in_time_team_features(team_games)

    corrupted_raw = team_games.copy()
    mask = corrupted_raw["week"] >= corrupt_from_week
    for col in EFFICIENCY_COLS:
        corrupted_raw.loc[mask, col] = corrupted_raw.loc[mask, col] * 1000 + 999
    corrupted = point_in_time_team_features(corrupted_raw)

    key = ["season", "team", "week", "game_id"]
    a = clean.sort_values(key).reset_index(drop=True)
    b = corrupted.sort_values(key).reset_index(drop=True)

    past = a["week"] < corrupt_from_week
    for col in PIT_COLS:
        diff = (a.loc[past, col].to_numpy() - b.loc[past, col].to_numpy())
        max_abs = np.nanmax(np.abs(diff)) if past.any() else 0.0
        assert max_abs < 1e-12, f"LEAK in {col}: past features moved by {max_abs}"
    print(f"PASS  no future leak (corrupted week >= {corrupt_from_week}, "
          f"{int(past.sum())} past team-games checked, all unchanged)")


def test_first_game_equals_prior():
    team_games, _ = make_synthetic()
    feats = point_in_time_team_features(team_games)
    first = feats[feats["n_prior"] == 0]
    for col in EFFICIENCY_COLS:
        vals = first[f"{col}_pit"].to_numpy()
        assert np.allclose(vals, DEFAULT_PRIOR[col], atol=1e-12), \
            f"first-game {col}_pit != prior {DEFAULT_PRIOR[col]}"
    print(f"PASS  first game equals prior ({len(first)} first-games checked)")


if __name__ == "__main__":
    test_no_future_leak()
    test_first_game_equals_prior()
    print("\nAll leakage checks passed.")
