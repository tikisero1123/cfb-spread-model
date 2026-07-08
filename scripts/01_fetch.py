"""Pull raw data from CFBD and cache it to data/raw/.

Usage:  python scripts/01_fetch.py 2021 2022 2023 2024
Needs CFBD_API_KEY in your environment or a .env file.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cfb.fetch_data import build_raw

def main():
    years = [int(a) for a in sys.argv[1:]] or [2021, 2022, 2023, 2024]
    print("Fetching:", years)
    team_games, games = build_raw(years)
    team_games.to_parquet("data/raw/team_games.parquet", index=False)
    games.to_parquet("data/raw/games.parquet", index=False)
    print(f"Wrote data/raw/team_games.parquet ({len(team_games)} rows)")
    print(f"Wrote data/raw/games.parquet ({len(games)} rows)")

if __name__ == "__main__":
    main()
