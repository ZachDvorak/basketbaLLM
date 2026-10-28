"""Load your Kaggle CSVs and confirm the agent's views work.

    python src/check_data.py [folder]        # folder defaults to $NBA_DATA_DIR, then ./data

Prints what the data covers, row counts per view, and a few sanity checks. Read it before running the eval.
"""
import sys

from db import NBADatabase


def main(folder=None):
    try:
        db = NBADatabase(folder)
    except FileNotFoundError as exc:
        sys.exit(str(exc))

    print(f"Data folder: {db.data_dir}")
    print(db.coverage(), "\n")
    for view in ["player_season", "player_season_team", "team_season", "league_season", "awards", "all_star",
                 "all_league_teams", "draft", "players", "team_abbrev"]:
        print(f"  {view:<20}{db.run_sql(f'SELECT count(*) FROM {view}')[1][0][0]:>8,} rows")

    checks = {
        "player_season has one row per player per season per league":
            "SELECT count(*) = count(DISTINCT (season, lg, player_id)) FROM player_season",
        "team_season has no 'League Average' rows":
            "SELECT count(*) = 0 FROM team_season WHERE team_name = 'League Average'",
        "every player_season row has games played":
            "SELECT count(*) = 0 FROM player_season WHERE g IS NULL",
        "scoring stats are numbers (not text)":
            "SELECT typeof(any_value(ppg)) = 'DOUBLE' AND typeof(any_value(total_pts)) IN ('BIGINT','INTEGER') FROM player_season",
    }
    failed = 0
    print("\nSanity checks:")
    for label, sql in checks.items():
        ok = db.run_sql(sql)[1][0][0]
        failed += not ok
        print(f"  [{'ok' if ok else 'FAIL'}] {label}")

    latest = db.run_sql("SELECT max(season) FROM player_season WHERE lg = 'NBA'")[1][0][0]
    print(f"\nLatest NBA season in the data: {latest - 1}-{latest % 100:02d} (season = {latest}). "
          "Top 3 scorers that season (min 50 games), to compare with Basketball-Reference:")
    for name, ppg in db.run_sql(
            f"SELECT player, ppg FROM player_season WHERE lg='NBA' AND season={latest} AND g>=50 "
            "ORDER BY ppg DESC LIMIT 3")[1]:
        print(f"  {name:<28}{ppg}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
