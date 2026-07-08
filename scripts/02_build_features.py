"""Build the leak-free model table from cached raw data.

Usage:  python scripts/02_build_features.py
Reads data/raw/, writes data/processed/model_table.parquet.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
from cfb.features import point_in_time_team_features, build_model_table
from cfb.config import MIN_WEEK, SHRINK_K

def main():
    team_games = pd.read_parquet("data/raw/team_games.parquet")
    games = pd.read_parquet("data/raw/games.parquet")
    feats = point_in_time_team_features(team_games, shrink_k=SHRINK_K)
    model_table = build_model_table(feats, games, min_week=MIN_WEEK)
    model_table.to_parquet("data/processed/model_table.parquet", index=False)
    print(f"Wrote data/processed/model_table.parquet ({len(model_table)} rows)")
    print(model_table.head().to_string(index=False))

if __name__ == "__main__":
    main()
