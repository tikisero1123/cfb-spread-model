"""
Synthetic CFB data with a KNOWN ground truth, so the pipeline can be tested
without the live API and the leakage test has something to bite on.

Each team gets a latent strength. Per-game stats and final scores are that
strength plus noise. None of this is realistic football. It only needs the
right SHAPE (one row per team per game, plus a games table) so the feature
engine and the leakage test exercise real code paths.
"""

from __future__ import annotations
import numpy as np
import pandas as pd


def make_synthetic(seasons=(2022, 2023), n_teams=16, weeks=13, seed=7):
    rng = np.random.default_rng(seed)
    teams = [f"Team{i:02d}" for i in range(n_teams)]
    strength = {t: rng.normal(0, 1) for t in teams}

    team_rows = []
    game_rows = []
    gid = 0
    for season in seasons:
        for week in range(1, weeks + 1):
            order = rng.permutation(teams)
            for i in range(0, n_teams, 2):
                home, away = order[i], order[i + 1]
                gid += 1
                sh, sa = strength[home], strength[away]
                hfa = 2.5  # home field worth ~2.5 pts of margin

                margin = (sh - sa) * 7 + hfa + rng.normal(0, 10)
                base = 28
                home_pts = max(0, round(base + margin / 2 + rng.normal(0, 3)))
                away_pts = max(0, round(base - margin / 2 + rng.normal(0, 3)))

                # Market spread = truth-ish minus small noise, home perspective.
                spread_home = -round(((sh - sa) * 7 + hfa) * 2) / 2 + rng.normal(0, 1)

                def stats_for(s, opp_s):
                    return dict(
                        off_ppa=0.15 * s + rng.normal(0, 0.1),
                        def_ppa=0.15 * opp_s + rng.normal(0, 0.1),
                        off_success_rate=0.43 + 0.03 * s + rng.normal(0, 0.02),
                        def_success_rate=0.43 + 0.03 * opp_s + rng.normal(0, 0.02),
                        off_explosiveness=1.6 + 0.1 * s + rng.normal(0, 0.05),
                        def_explosiveness=1.6 + 0.1 * opp_s + rng.normal(0, 0.05),
                    )

                hs = stats_for(sh, sa)
                as_ = stats_for(sa, sh)
                team_rows.append(dict(game_id=gid, season=season, week=week, team=home,
                                      points_for=home_pts, points_against=away_pts, **hs))
                team_rows.append(dict(game_id=gid, season=season, week=week, team=away,
                                      points_for=away_pts, points_against=home_pts, **as_))
                game_rows.append(dict(game_id=gid, season=season, week=week,
                                      home_team=home, away_team=away, neutral_site=False,
                                      home_points=home_pts, away_points=away_pts,
                                      spread_home=spread_home))

    return pd.DataFrame(team_rows), pd.DataFrame(game_rows)


if __name__ == "__main__":
    tg, g = make_synthetic()
    print("team-games:", tg.shape, "| games:", g.shape)
    print(tg.head(3).to_string())
