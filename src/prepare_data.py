"""Convert a downloaded Kaggle (or any) box-score dataset into data/player_games.csv and data/team_games.csv.

    python src/inspect_csvs.py /content/my-dataset                      # 1. look at the columns
    cp data_mapping.example.json data_mapping.json                     # 2. edit the mapping to match
    python src/prepare_data.py --src /content/my-dataset --mapping data_mapping.json

The mapping file says which CSV holds the player box scores, which source column maps to which of our names,
and any constant values (for example season_type when the file only has regular season games).
If the dataset has no team game file, set "team_games": "derive" and the team table is built by summing the
player rows for each team and game.

The script cleans what it can: dates to YYYY-MM-DD, "35:12" minutes to 35.2, win flags (1/0/True/False) to W/L,
season years to "2023-24" labels. It stops with a clear message if anything the agent truly needs is missing.
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from schema import HARD, SOFT, STAT_COLS

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TEAM_KEYS = ["season", "season_type", "team_id", "team_abbreviation", "team_name", "game_id", "game_date",
             "matchup", "wl"]


def season_label(start_year):
    return f"{int(start_year)}-{(int(start_year) + 1) % 100:02d}"


def to_minutes(series):
    if not pd.api.types.is_numeric_dtype(series):
        def convert(v):
            if pd.isna(v):
                return None
            text = str(v).strip()
            if ":" in text:
                minutes, seconds = text.split(":")[:2]
                return round(int(minutes) + int(seconds) / 60, 1)
            try:
                return float(text)
            except ValueError:
                return None
        return series.map(convert)
    return series


def to_wl(series):
    def convert(v):
        text = str(v).strip().upper()
        if text in ("W", "WIN", "1", "1.0", "TRUE"):
            return "W"
        if text in ("L", "LOSS", "0", "0.0", "FALSE"):
            return "L"
        return None
    return series.map(convert)


def load_table(src, spec, season_year_is):
    frame = pd.read_csv(Path(src) / spec["file"], low_memory=False)
    lower = {c.lower(): c for c in frame.columns}
    rename = {}
    for source, target in spec.get("rename", {}).items():
        actual = source if source in frame.columns else lower.get(source.lower())
        if actual is None:
            sys.exit(f"{spec['file']}: mapping refers to column '{source}' which is not in the file. "
                     f"Columns are: {list(frame.columns)}")
        rename[actual] = target
    frame = frame.rename(columns=rename)
    frame.columns = [c.lower() for c in frame.columns]
    for column, value in spec.get("defaults", {}).items():
        if column not in frame.columns:
            frame[column] = value

    if "game_date" in frame:
        dates = pd.to_datetime(frame["game_date"], errors="coerce")
        frame["game_date"] = dates.dt.strftime("%Y-%m-%d")
        if "season" not in frame:
            start = dates.dt.year.where(dates.dt.month >= 8, dates.dt.year - 1)
            frame["season"] = start.map(lambda y: season_label(y) if pd.notna(y) else None)
    if "season" in frame and pd.api.types.is_numeric_dtype(frame["season"]):
        offset = 0 if season_year_is == "start" else -1
        frame["season"] = frame["season"].map(lambda y: season_label(y + offset) if pd.notna(y) else None)
    if "min" in frame:
        frame["min"] = to_minutes(frame["min"])
    if "wl" in frame:
        frame["wl"] = to_wl(frame["wl"])
    if "reb" not in frame and {"oreb", "dreb"} <= set(frame.columns):
        frame["reb"] = frame["oreb"] + frame["dreb"]
    return frame


def finish(frame, name, notes):
    if "team_name" not in frame and "team_abbreviation" in frame:
        frame["team_name"] = frame["team_abbreviation"]
        notes.append(f"{name}: no team_name column, using team_abbreviation (questions that use full team names will fail)")
    if "team_id" not in frame and "team_abbreviation" in frame:
        frame["team_id"] = frame["team_abbreviation"]
    for column in sorted(SOFT):
        if column not in frame:
            frame[column] = None
            notes.append(f"{name}: no '{column}' column, filled with empty values")
    missing = sorted(HARD - set(frame.columns))
    if name == "team_games":
        missing = [m for m in missing if m not in ("player_id", "player_name")]
    if missing:
        sys.exit(f"{name}: still missing required columns {missing}. Add them to the mapping 'rename' or "
                 f"'defaults', or tell your helper what the file contains.")
    return frame


def derive_team_games(players):
    keys = [k for k in TEAM_KEYS if k in players.columns]
    stats = [c for c in STAT_COLS if c in players.columns and c != "plus_minus"]
    grouped = players.groupby(keys, dropna=False, as_index=False)[stats].sum(min_count=1)
    grouped["plus_minus"] = None
    return grouped


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--src", required=True, help="folder with the downloaded CSVs")
    parser.add_argument("--mapping", required=True, help="JSON mapping file (see data_mapping.example.json)")
    args = parser.parse_args()

    mapping = json.loads(Path(args.mapping).read_text())
    year_is = mapping.get("season_year_is", "start")
    notes = []

    players = finish(load_table(args.src, mapping["player_games"], year_is), "player_games", notes)
    team_spec = mapping.get("team_games", "derive")
    if team_spec == "derive":
        teams = derive_team_games(players)
        notes.append("team_games: built by summing player rows per team and game (plus_minus left empty)")
    else:
        teams = load_table(args.src, team_spec, year_is)
    teams = finish(teams, "team_games", notes)

    bad = players["game_date"].isna().sum()
    if bad:
        notes.append(f"player_games: {bad} rows have unreadable dates")
    dupes = players.duplicated(subset=["game_id", "player_id"]).sum()
    if dupes:
        notes.append(f"player_games: {dupes} duplicate (game_id, player_id) rows. Check the dataset or the mapping")
    teams_per_game = teams.groupby("game_id").size()
    if (teams_per_game != 2).any():
        notes.append(f"team_games: {(teams_per_game != 2).sum()} games do not have exactly 2 team rows "
                     "(team_season opponent points will be wrong or missing for them)")

    DATA_DIR.mkdir(exist_ok=True)
    players.to_csv(DATA_DIR / "player_games.csv", index=False)
    teams.to_csv(DATA_DIR / "team_games.csv", index=False)

    print(f"player_games: {len(players):,} rows | seasons {sorted(players.season.dropna().unique())[:3]} ... "
          f"{sorted(players.season.dropna().unique())[-1:]}")
    print(f"team_games:   {len(teams):,} rows | {teams.game_id.nunique():,} games")
    print(f"season_type values: {sorted(players.season_type.dropna().unique())}")
    for note in notes:
        print("NOTE:", note)
    print("\nNext: python src/evaluate.py --check-gold   (questions whose columns are missing are skipped)")


if __name__ == "__main__":
    main()
