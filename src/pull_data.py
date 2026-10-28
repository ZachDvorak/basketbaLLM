"""Download NBA data with nba_api and save tidy CSVs under data/.

Run in Colab or on your own machine (stats.nba.com must be reachable):

    python src/pull_data.py                              # last 5 seasons, regular season + playoffs
    python src/pull_data.py --seasons 2023-24 2024-25    # pick seasons
    python src/pull_data.py --proxy http://user:pw@host:port

Outputs (all column names lowercase):
    data/player_games.csv   one row per player per game  (box scores)
    data/team_games.csv     one row per team per game
    data/teams.csv          30 teams
    data/players.csv        player directory (optional table)
Raw per-season downloads are cached in data/raw/, so re-runs only fetch what is missing.
"""
import argparse
import sys
import time
from pathlib import Path

import pandas as pd
from nba_api.stats.endpoints import commonallplayers, leaguegamelog
from nba_api.stats.static import teams as static_teams

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RAW_DIR = DATA_DIR / "raw"

DEFAULT_SEASONS = ["2021-22", "2022-23", "2023-24", "2024-25", "2025-26"]
SEASON_TYPES = ["Regular Season", "Playoffs"]

BOX_STATS = {
    "game_id", "game_date", "matchup", "wl", "min", "fgm", "fga", "fg3m", "fg3a",
    "ftm", "fta", "oreb", "dreb", "reb", "ast", "stl", "blk", "tov", "pf", "pts",
    "plus_minus", "team_id", "team_abbreviation",
}
REQUIRED_COLS = {
    "player_games": BOX_STATS | {"player_id", "player_name"},
    "team_games": BOX_STATS | {"team_name"},
}


def fetch_game_log(season, season_type, scope, proxy, retries=4, pause=1.5):
    """scope is 'P' (player box scores) or 'T' (team game logs). Cached in data/raw/."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cache = RAW_DIR / f"{scope}_{season}_{season_type.replace(' ', '')}.csv"
    if cache.exists():
        return pd.read_csv(cache)

    for attempt in range(1, retries + 1):
        try:
            frame = leaguegamelog.LeagueGameLog(
                season=season,
                season_type_all_star=season_type,
                player_or_team_abbreviation=scope,
                timeout=60,
                proxy=proxy,
            ).get_data_frames()[0]
            frame.to_csv(cache, index=False)
            time.sleep(pause)  # be polite; the API rate-limits aggressive callers
            return frame
        except Exception as exc:  # nba_api surfaces requests/JSON errors as generic exceptions
            wait = 5 * attempt
            print(f"  attempt {attempt}/{retries} failed for {season} {season_type} {scope}: "
                  f"{type(exc).__name__}: {exc}")
            if attempt == retries:
                raise
            print(f"  retrying in {wait}s")
            time.sleep(wait)


def tidy(frame, season, season_type):
    frame = frame.copy()
    frame.columns = [c.lower() for c in frame.columns]
    frame = frame.drop(columns=["video_available"], errors="ignore")
    frame.insert(0, "season_type", season_type)
    frame.insert(0, "season", season)
    return frame


def validate(name, frame):
    missing = REQUIRED_COLS[name] - set(frame.columns)
    if missing:
        sys.exit(f"{name}: the API response is missing expected columns {sorted(missing)}. "
                 f"Columns received: {sorted(frame.columns)}")
    dupes = frame.duplicated(subset=["game_id", "player_id" if name == "player_games" else "team_id"]).sum()
    if dupes:
        sys.exit(f"{name}: {dupes} duplicate (game, entity) rows found")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seasons", nargs="+", default=DEFAULT_SEASONS, help="e.g. 2023-24 2024-25")
    parser.add_argument("--season-types", nargs="+", default=SEASON_TYPES)
    parser.add_argument("--proxy", default=None, help="optional http(s) proxy URL")
    args = parser.parse_args()

    DATA_DIR.mkdir(exist_ok=True)
    player_parts, team_parts = [], []

    try:
        for season in args.seasons:
            for season_type in args.season_types:
                print(f"{season} {season_type}")
                for scope, parts in (("P", player_parts), ("T", team_parts)):
                    frame = fetch_game_log(season, season_type, scope, args.proxy)
                    if frame.empty:
                        print(f"  no {scope} rows (season not played yet?)")
                        continue
                    parts.append(tidy(frame, season, season_type))
                    print(f"  {scope}: {len(frame):,} rows")

        print("players directory")
        directory = commonallplayers.CommonAllPlayers(
            is_only_current_season=0, timeout=60, proxy=args.proxy
        ).get_data_frames()[0]
        directory.columns = [c.lower() for c in directory.columns]
        directory.to_csv(DATA_DIR / "players.csv", index=False)
    except Exception as exc:
        sys.exit(
            f"\nDownload failed: {type(exc).__name__}: {exc}\n\n"
            "stats.nba.com often blocks cloud IP ranges (Colab included) with timeouts. Options:\n"
            "  1. Re-run this script (results are cached, so it resumes where it stopped).\n"
            "  2. Run it on your laptop, then upload the data/ folder to Colab or Drive.\n"
            "  3. Pass --proxy with a residential or other proxy you are allowed to use.\n"
            "  4. Build the same two CSVs from another source (e.g. a Kaggle NBA box-score "
            "dataset) using the column names in docs/data_dictionary.md."
        )

    if not player_parts or not team_parts:
        sys.exit("No data was downloaded.")

    player_games = pd.concat(player_parts, ignore_index=True)
    team_games = pd.concat(team_parts, ignore_index=True)
    validate("player_games", player_games)
    validate("team_games", team_games)

    player_games.to_csv(DATA_DIR / "player_games.csv", index=False)
    team_games.to_csv(DATA_DIR / "team_games.csv", index=False)
    pd.DataFrame(static_teams.get_teams()).to_csv(DATA_DIR / "teams.csv", index=False)

    print("\nDone.")
    print(f"  player_games: {len(player_games):,} rows, {player_games.player_id.nunique():,} players")
    print(f"  team_games:   {len(team_games):,} rows, {team_games.game_id.nunique():,} games")
    print(f"  dates: {team_games.game_date.min()} -> {team_games.game_date.max()}")


if __name__ == "__main__":
    main()
