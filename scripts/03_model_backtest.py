"""Train the model walk-forward and grade it against the spread.

Usage:  python3 scripts/03_model_backtest.py
Reads data/processed/model_table.parquet (run 02_build_features.py first).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
from cfb.model import walk_forward_backtest, grade

def main():
    mt = pd.read_parquet("data/processed/model_table.parquet")
    print(f"Loaded {len(mt)} games across seasons: {sorted(mt['season'].unique())}")
    print("\nWalk-forward (train on past seasons, predict the next):")
    preds = walk_forward_backtest(mt)
    preds.to_parquet("outputs/backtest_predictions.parquet", index=False)
    grade(preds)
    print("\nWrote outputs/backtest_predictions.parquet")

if __name__ == "__main__":
    main()
