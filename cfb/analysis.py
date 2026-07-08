"""Market comparison and pocket analysis."""
import pandas as pd

P5 = {"SEC", "Big Ten", "Big 12", "ACC", "Pac-12"}


def matchup_type(row, fbs_teams):
    """Classify a game by division tier. Requires conf_h / conf_a columns."""
    h, a = row["home_team"] in fbs_teams, row["away_team"] in fbs_teams
    if h and a:
        hp5 = row["conf_h"] in P5 if pd.notna(row["conf_h"]) else False
        ap5 = row["conf_a"] in P5 if pd.notna(row["conf_a"]) else False
        if hp5 and ap5:
            return "P5 vs P5"
        if not hp5 and not ap5:
            return "G5 vs G5"
        return "P5 vs G5"
    if h or a:
        return "FBS vs FCS"
    return "FCS vs FCS"


def pockets(df, by):
    """Model-vs-market error summary grouped by any column."""
    g = df.groupby(by, observed=True).agg(
        games=("margin", "size"),
        model_mae=("model_error", "mean"),
        vegas_mae=("vegas_error", "mean"),
        closer_pct=("model_closer", "mean"),
    )
    g["gap"] = (g["model_mae"] - g["vegas_mae"]).round(3)
    g["closer_pct"] = (g["closer_pct"] * 100).round(1)
    return g[["games", "model_mae", "vegas_mae", "gap", "closer_pct"]].round(3)
