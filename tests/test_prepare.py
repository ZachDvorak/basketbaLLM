"""prepare_data.py on a FAKE Kaggle-style dataset: odd column names, 'MM:SS' minutes, win flags, no team file."""
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from make_synthetic import make  # noqa: E402


def kaggle_style(tmp_path):
    fake = make(tmp_path / "fake", games_per_team=6)
    p = pd.read_csv(fake / "player_games.csv")
    p = p[p.season_type == "Regular Season"]
    p["season_year"] = p.season.str[:4].astype(int)
    p["MIN"] = p["min"].map(lambda m: f"{int(m)}:30")
    p["GAME_DATE"] = pd.to_datetime(p.game_date).dt.strftime("%m/%d/%Y")
    p["win"] = (p.wl == "W").astype(int)
    p = p.rename(columns={"player_id": "personId", "player_name": "playerName", "team_abbreviation": "tri",
                          "team_name": "teamName", "game_id": "gameId", "pts": "points", "ast": "assists",
                          "reb": "rebounds", "stl": "steals", "blk": "blocks", "tov": "turnovers",
                          "fgm": "fgMade", "fga": "fgAtt", "fg3m": "tpMade", "fg3a": "tpAtt", "ftm": "ftMade",
                          "fta": "ftAtt"})
    src = tmp_path / "kaggle"
    src.mkdir()
    p.drop(columns=["min", "game_date", "wl", "season", "season_type", "matchup", "team_id"]).to_csv(
        src / "box.csv", index=False)
    mapping = {"season_year_is": "start", "player_games": {"file": "box.csv", "rename": {
        "personId": "player_id", "playerName": "player_name", "tri": "team_abbreviation", "teamName": "team_name",
        "gameId": "game_id", "GAME_DATE": "game_date", "MIN": "min", "win": "wl", "season_year": "season",
        "points": "pts", "assists": "ast", "rebounds": "reb", "steals": "stl", "blocks": "blk",
        "turnovers": "tov", "fgMade": "fgm", "fgAtt": "fga", "tpMade": "fg3m", "tpAtt": "fg3a",
        "ftMade": "ftm", "ftAtt": "fta"}, "defaults": {"season_type": "Regular Season"}}, "team_games": "derive"}
    (tmp_path / "map.json").write_text(json.dumps(mapping))
    return src, tmp_path / "map.json"


def test_prepare_then_load_and_query(tmp_path, monkeypatch):
    src, mapping = kaggle_style(tmp_path)
    import prepare_data
    monkeypatch.setattr(prepare_data, "DATA_DIR", tmp_path / "out")
    monkeypatch.setattr(sys, "argv", ["prepare_data", "--src", str(src), "--mapping", str(mapping)])
    prepare_data.main()

    from db import NBADatabase
    db = NBADatabase(tmp_path / "out")
    _, rows, _ = db.run_sql(
        "SELECT season, min, wl FROM player_games WHERE player_name='Stephen Curry' LIMIT 3")
    assert rows and all(len(s) == 7 and 0 < m < 60 and w in "WL" for s, m, w in rows)
    # derived team table: two rows per game, points equal the sum of player points
    _, bad, _ = db.run_sql(
        "SELECT count(*) FROM team_games t WHERE pts <> (SELECT sum(pts) FROM player_games p "
        "WHERE p.game_id=t.game_id AND p.team_abbreviation=t.team_abbreviation)")
    assert bad[0][0] == 0
    db.run_sql("SELECT * FROM team_season LIMIT 1")
    db.run_sql("SELECT * FROM player_season LIMIT 1")


def test_missing_required_column_gives_clear_error(tmp_path, monkeypatch, capsys):
    import pytest
    src, mapping = kaggle_style(tmp_path)
    spec = json.loads(mapping.read_text())
    del spec["player_games"]["rename"]["points"]
    mapping.write_text(json.dumps(spec))
    import prepare_data
    monkeypatch.setattr(prepare_data, "DATA_DIR", tmp_path / "out")
    monkeypatch.setattr(sys, "argv", ["prepare_data", "--src", str(src), "--mapping", str(mapping)])
    with pytest.raises(SystemExit) as exc:
        prepare_data.main()
    assert "pts" in str(exc.value)


def test_inspect_runs(tmp_path, capsys):
    src, _ = kaggle_style(tmp_path)
    import inspect_csvs
    inspect_csvs.main(src)
    out = capsys.readouterr().out
    assert "box.csv" in out and "playerName" in out
