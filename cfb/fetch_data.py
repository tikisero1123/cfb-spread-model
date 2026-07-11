"""
Pull raw data from the CollegeFootballData API (v2) and write it into the schema
the feature engine expects.

CFBD moved to API v2 in 2025 and renamed fields to camelCase (home_points became
homePoints, etc.). To keep this from breaking again every time the API shifts,
every field is read with _pick(), which accepts several possible names and takes
whichever one is actually present. So this works against v2 and would still work
if a field reverts to the old snake_case name.

Endpoints used:
  /games                  schedule + final scores
  /lines                  betting lines (spread, home perspective)
  /stats/game/advanced    per-team-per-game ppa / success rate / explosiveness

Output (written to data/raw/):
  team_games.parquet   one row per team per game (cfb.features.EFFICIENCY_COLS)
  games.parquet        one row per game (home perspective, with spread_home)
"""

from __future__ import annotations
import time
import requests
import pandas as pd

from cfb.config import CFBD_BASE_URL, require_key, MIN_WEEK


def _pick(d: dict, *keys, default=None):
    """Return the first key that exists and is not None. Lets one parser handle
    camelCase (v2) and snake_case (old) without caring which the API sent."""
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def _get(path: str, params: dict) -> list[dict]:
    key = require_key()
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    url = f"{CFBD_BASE_URL}{path}"
    resp = requests.get(url, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    time.sleep(0.4)  # be polite to the API
    data = resp.json()
    if not isinstance(data, list):
        raise RuntimeError(f"{path} did not return a list. Got: {str(data)[:200]}")
    return data


def fetch_games(year: int, season_type: str = "regular") -> pd.DataFrame:
    raw = _get("/games", {"year": year, "seasonType": season_type})
    rows = []
    for g in raw:
        hp = _pick(g, "homePoints", "home_points")
        ap = _pick(g, "awayPoints", "away_points")
        if hp is None or ap is None:
            continue  # game not played yet
        rows.append(dict(
            game_id=_pick(g, "id", "gameId"),
            season=_pick(g, "season"),
            week=_pick(g, "week"),
            home_team=_pick(g, "homeTeam", "home_team"),
            away_team=_pick(g, "awayTeam", "away_team"),
            neutral_site=bool(_pick(g, "neutralSite", "neutral_site", default=False)),
            home_points=hp,
            away_points=ap,
        ))
    return pd.DataFrame(rows)


def fetch_lines(year: int, provider: str = "consensus") -> pd.DataFrame:
    """Spread from the home perspective. Prefers the chosen provider, falls back
    to the first available. CFBD 'spread' is already home-relative."""
    raw = _get("/lines", {"year": year})
    rows = []
    for g in raw:
        lines = _pick(g, "lines", default=[]) or []
        if not lines:
            continue
        chosen = next((l for l in lines if _pick(l, "provider") == provider), lines[0])
        spread = _pick(chosen, "spread")
        if spread is None:
            continue
        rows.append(dict(game_id=_pick(g, "id", "gameId"), spread_home=float(spread)))
    return pd.DataFrame(rows)


def fetch_advanced_stats(year: int) -> pd.DataFrame:
    """Per-team-per-game advanced stats -> one row per team per game."""
    raw = _get("/stats/game/advanced", {"year": year})
    rows = []
    for s in raw:
        off = _pick(s, "offense", default={}) or {}
        deff = _pick(s, "defense", default={}) or {}
        rows.append(dict(
            game_id=_pick(s, "gameId", "game_id"),
            team=_pick(s, "team"),
            off_ppa=_pick(off, "ppa"),
            def_ppa=_pick(deff, "ppa"),
            off_success_rate=_pick(off, "successRate", "success_rate"),
            def_success_rate=_pick(deff, "successRate", "success_rate"),
            off_explosiveness=_pick(off, "explosiveness"),
            def_explosiveness=_pick(deff, "explosiveness"),
        ))
    return pd.DataFrame(rows)


def build_raw(years: list[int], season_type: str = "regular") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fetch and assemble the two raw tables the feature engine reads."""
    games_all, team_all = [], []
    for y in years:
        games = fetch_games(y, season_type)
        print(f"  {y}: {len(games)} games", flush=True)
        if games.empty:
            raise RuntimeError(
                f"No completed games came back for {y}. Either the season hasn't "
                f"happened, or a field name changed again."
            )

        lines = fetch_lines(y)
        print(f"  {y}: {len(lines)} games with a spread", flush=True)
        adv = fetch_advanced_stats(y)
        print(f"  {y}: {len(adv)} team-game advanced stat rows", flush=True)

        games = games.merge(lines, on="game_id", how="left")
        games_all.append(games)

        # Attach points scored/allowed to each team-game from the games table.
        long = []
        for _, g in games.iterrows():
            long.append(dict(game_id=g["game_id"], season=g["season"], week=g["week"],
                             team=g["home_team"], points_for=g["home_points"],
                             points_against=g["away_points"]))
            long.append(dict(game_id=g["game_id"], season=g["season"], week=g["week"],
                             team=g["away_team"], points_for=g["away_points"],
                             points_against=g["home_points"]))
        tg = pd.DataFrame(long).merge(adv, on=["game_id", "team"], how="left")
        team_all.append(tg)

    team_games = pd.concat(team_all, ignore_index=True)
    games = pd.concat(games_all, ignore_index=True)

    eff = ["off_ppa", "def_ppa", "off_success_rate", "def_success_rate",
           "off_explosiveness", "def_explosiveness"]
    before = len(team_games)
    team_games = team_games.dropna(subset=eff).reset_index(drop=True)
    print(f"  kept {len(team_games)} of {before} team-games with full stats", flush=True)
    return team_games, games


def fetch_talent(years):
    """247Sports talent composite, z-scored within season. Deduped at source
    (the /talent endpoint returns some team-seasons twice)."""
    import pandas as pd
    rows = []
    for y in years:
        for r in _get("/talent", {"year": y}):
            team = r.get("team") or r.get("school")
            val = r.get("talent")
            if team is not None and val is not None:
                rows.append((y, team, float(val)))
    df = pd.DataFrame(rows, columns=["season", "team", "talent"])
    df = df.drop_duplicates(subset=["season", "team"]).reset_index(drop=True)
    df["talent_z"] = df.groupby("season")["talent"].transform(
        lambda s: (s - s.mean()) / s.std())
    return df


def fetch_conferences(years):
    """FBS team -> conference mapping per season."""
    import pandas as pd
    rows = []
    for y in years:
        for r in _get("/teams/fbs", {"year": y}):
            team = r.get("school") or r.get("team")
            conf = r.get("conference")
            if team and conf:
                rows.append((y, team, conf))
    return pd.DataFrame(rows, columns=["season", "team", "conference"])


def fetch_lines_history(years):
    """Betting lines per game per provider from /lines. Keeps opener and
    closer where the provider reports both. Spread is from the home team's
    perspective (negative = home favored), matching CFBD convention."""
    import pandas as pd
    rows = []
    for y in years:
        for g in _get("/lines", {"year": y}):
            gid = _pick(g, "id", "gameId")
            for ln in (g.get("lines") or []):
                rows.append({
                    "game_id": gid,
                    "season": _pick(g, "season"),
                    "week": _pick(g, "week"),
                    "home_team": _pick(g, "homeTeam", "home_team"),
                    "away_team": _pick(g, "awayTeam", "away_team"),
                    "provider": _pick(ln, "provider"),
                    "spread_close": _pick(ln, "spread"),
                    "spread_open": _pick(ln, "spreadOpen", "spread_open"),
                    "total_close": _pick(ln, "overUnder", "over_under"),
                    "total_open": _pick(ln, "overUnderOpen", "over_under_open"),
                })
    df = pd.DataFrame(rows)
    for c in ["spread_close", "spread_open", "total_close", "total_open"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.drop_duplicates(subset=["game_id", "provider"]).reset_index(drop=True)
    return df


def fetch_team_logos():
    """Team -> logo URL from /teams (ESPN-hosted images)."""
    import pandas as pd
    rows = []
    for t in _get("/teams", {}):
        team = t.get("school") or t.get("team")
        logos = t.get("logos") or []
        if team and logos:
            rows.append((team, logos[0]))
    return pd.DataFrame(rows, columns=["team", "logo"])


def fetch_schedule(year, weeks=None):
    """Scheduled games for a season from /games (regular season)."""
    import pandas as pd
    rows = []
    for g in _get("/games", {"year": year, "seasonType": "regular"}):
        wk = _pick(g, "week")
        if weeks and wk not in weeks:
            continue
        rows.append({
            "game_id": _pick(g, "id", "gameId"),
            "season": year,
            "week": wk,
            "home_team": _pick(g, "homeTeam", "home_team"),
            "away_team": _pick(g, "awayTeam", "away_team"),
            "start_date": _pick(g, "startDate", "start_date"),
        })
    return pd.DataFrame(rows)


def fetch_team_logos():
    """Team -> logo URL from /teams (ESPN-hosted images)."""
    import pandas as pd
    rows = []
    for t in _get("/teams", {}):
        team = t.get("school") or t.get("team")
        logos = t.get("logos") or []
        if team and logos:
            rows.append((team, logos[0]))
    return pd.DataFrame(rows, columns=["team", "logo"])


def fetch_schedule(year, weeks=None):
    """Scheduled games for a season from /games (regular season)."""
    import pandas as pd
    rows = []
    for g in _get("/games", {"year": year, "seasonType": "regular"}):
        wk = _pick(g, "week")
        if weeks and wk not in weeks:
            continue
        rows.append({
            "game_id": _pick(g, "id", "gameId"),
            "season": year,
            "week": wk,
            "home_team": _pick(g, "homeTeam", "home_team"),
            "away_team": _pick(g, "awayTeam", "away_team"),
            "start_date": _pick(g, "startDate", "start_date"),
        })
    return pd.DataFrame(rows)


def fetch_lines_market(years):
    """Per-game market snapshot from /lines: spread, total, moneylines.
    Uses current/closing values -- for future games these are the live numbers."""
    import pandas as pd
    rows = []
    for y in years:
        for g in _get("/lines", {"year": y}):
            gid = _pick(g, "id", "gameId")
            for ln in (g.get("lines") or []):
                rows.append({
                    "game_id": gid,
                    "provider": _pick(ln, "provider"),
                    "lines_home": _pick(g, "homeTeam", "home_team"),
                    "spread": _pick(ln, "spread"),
                    "total": _pick(ln, "overUnder", "over_under"),
                    "ml_home": _pick(ln, "homeMoneyline", "home_moneyline"),
                    "ml_away": _pick(ln, "awayMoneyline", "away_moneyline"),
                })
    df = pd.DataFrame(rows)
    for c in ["spread", "total", "ml_home", "ml_away"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.drop_duplicates(subset=["game_id", "provider"]).reset_index(drop=True)
