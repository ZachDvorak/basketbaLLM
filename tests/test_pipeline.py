"""Offline tests: data loading, views, SQL guard, gold SQL and grading, all on a tiny FAKE dataset."""
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from db import NBADatabase, format_rows  # noqa: E402
from evaluate import auto_grade, load_questions, numbers_in  # noqa: E402
from make_fixture import make  # noqa: E402
from schema import FILES  # noqa: E402


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory):
    return make(tmp_path_factory.mktemp("fake_nba"))


@pytest.fixture(scope="module")
def db(data_dir):
    return NBADatabase(data_dir)


def rows(db, sql):
    return db.run_sql(sql)[1]


def test_season_label_uses_end_year_convention(db):
    assert rows(db, "SELECT season_label(2024), season_label(2000), season_label(1947)")[0] == (
        "2023-24", "1999-00", "1946-47")


def test_traded_player_is_deduplicated_in_player_season(db):
    assert rows(db, "SELECT team, g, ppg FROM player_season WHERE player='James Harden' AND season=2022") == [
        ("2TM", 65, 22.0)]
    assert rows(db, "SELECT count(*) FROM player_season_team WHERE player='James Harden' AND season=2022") == [(3,)]


def test_career_sum_does_not_double_count_trade(db):
    assert rows(db, "SELECT sum(total_pts) FROM player_season WHERE player_id='hardeja01'") == [(1430,)]


def test_na_becomes_null_and_stays_numeric(db):
    assert rows(db, "SELECT spg, total_stl, bpm FROM player_season WHERE player_id='timerol01' AND lg='NBA'") == [
        (None, None, None)]
    assert rows(db, "SELECT typeof(ppg), typeof(per) FROM player_season LIMIT 1") == [("DOUBLE", "DOUBLE")]


def test_team_and_league_views(db):
    assert rows(db, "SELECT count(*) FROM team_season WHERE team_name='League Average'") == [(0,)]
    assert rows(db, "SELECT ppg_per_team FROM league_season WHERE season=2024 AND lg='NBA'") == [(114.2,)]
    assert rows(db, "SELECT wins, losses, win_pct, ppg, opp_ppg FROM team_season WHERE team_abbrev='BOS'") == [
        (64, 18, 0.78, 115.0, 110.0)]


def test_other_views(db):
    assert rows(db, "SELECT player FROM awards WHERE award='nba mvp' AND season=2024 AND winner") == [("Nikola Jokić",)]
    assert rows(db, "SELECT draft_year, overall_pick, college FROM draft") == [(2018, 3, None)]
    assert rows(db, "SELECT first_season, last_season, hall_of_famer FROM players") == [(2019, 2025, False)]


def test_coverage_and_live_schema_hide_raw_tables(db):
    assert "1946-47" not in db.coverage() and "1969-70" in db.coverage() and "2024-25" in db.coverage()
    schema = db.live_schema()
    assert "player_season (view)" in schema and "raw" not in schema


def test_name_matching_with_accents(db):
    assert rows(db, "SELECT count(DISTINCT player_id) FROM player_season WHERE strip_accents(player) ILIKE '%doncic%'") == [(1,)]


@pytest.mark.parametrize("bad", [
    "DROP VIEW player_season",
    "DELETE FROM raw.player_totals",
    "SELECT 1; DROP TABLE raw.awards",
    "COPY (SELECT 1) TO '/tmp/x.csv'",
    "SELECT * FROM read_csv('/etc/passwd')",
    "SET enable_external_access = true",
    "ATTACH '/tmp/evil.db'",
])
def test_guard_blocks_unsafe_sql(db, bad):
    with pytest.raises(ValueError):
        db.run_sql(bad)


def test_cte_allowed_truncation_and_errors(db):
    _, got, truncated = db.run_sql("WITH x AS (SELECT * FROM range(100)) SELECT * FROM x")
    assert len(got) == 50 and truncated
    assert "truncated" in format_rows(["a"], [(1,)] * 50, True)
    with pytest.raises(ValueError):
        db.run_sql("SELECT nonexistent_column FROM player_season")


def test_finds_csvs_in_subfolders_case_insensitively(data_dir, tmp_path):
    nested = tmp_path / "download" / "v7"
    shutil.copytree(data_dir, nested)
    for path in nested.glob("*.csv"):
        path.rename(path.with_name(path.name.lower()))
    assert rows(NBADatabase(tmp_path), "SELECT count(*) FROM player_season") != [(0,)]


def test_missing_file_gives_helpful_error(data_dir, tmp_path):
    shutil.copytree(data_dir, tmp_path / "d")
    (tmp_path / "d" / "Draft Pick History.csv").unlink()
    with pytest.raises(FileNotFoundError) as exc:
        NBADatabase(tmp_path / "d")
    assert "Draft Pick History.csv" in str(exc.value) and "inspect_csvs" in str(exc.value)


def test_missing_column_gives_helpful_error(data_dir, tmp_path):
    shutil.copytree(data_dir, tmp_path / "d")
    path = tmp_path / "d" / "Advanced.csv"
    path.write_text(path.read_text().replace("vorp", "vorp_renamed"))
    with pytest.raises(FileNotFoundError) as exc:
        NBADatabase(tmp_path / "d")
    assert "Advanced.csv" in str(exc.value) and "vorp" in str(exc.value)


def test_nonexistent_folder_gives_helpful_error(tmp_path):
    with pytest.raises(FileNotFoundError) as exc:
        NBADatabase(tmp_path / "nope")
    assert "none" in str(exc.value).lower()


def test_every_gold_query_is_valid_sql(db):
    gold = [q for q in load_questions() if q["gold_sql"].strip()]
    assert len(gold) >= 35
    for q in gold:
        db.run_sql(q["gold_sql"])  # raises if the SQL does not run against the schema


def test_unanswerable_questions_have_no_gold():
    assert sum(1 for q in load_questions() if q["category"] == "unanswerable" and not q["gold_sql"]) == 4


def test_every_expected_file_is_declared():
    assert len(FILES) == 12 and all(name.endswith(".csv") for name, _ in FILES.values())


def test_numbers_in_handles_commas_and_percent():
    assert 42184.0 in numbers_in("He scored 42,184 points.") and 61.7 in numbers_in("TS% was 61.7%.")


def test_auto_grade():
    assert auto_grade([("Luka Dončić", 33.9)], "Luka Dončić led at 33.9 ppg.", False)
    assert auto_grade([(0.65,)], "His true shooting was 65%.", False)
    assert auto_grade([("2015-16", 402)], "In 2015-16 he made 402 threes.", False)
    assert not auto_grade([("Luka Dončić", 33.9)], "Luka Dončić led at 31.0 ppg.", False)
    assert auto_grade([], "I don't have salary data.", True)
    assert not auto_grade([], "He earns $48 million.", True)
