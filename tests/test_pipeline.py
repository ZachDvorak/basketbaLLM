"""Offline tests: DuckDB layer, SQL guard, gold SQL, and grading logic on FAKE data."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from db import NBADatabase, format_rows  # noqa: E402
from evaluate import auto_grade, load_questions, numbers_in  # noqa: E402
from make_synthetic import make  # noqa: E402


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    return NBADatabase(make(tmp_path_factory.mktemp("fake_nba")))


def test_views_exist_and_aggregate(db):
    cols, rows, _ = db.run_sql(
        "SELECT games, ppg, total_pts FROM player_season WHERE player_name='Stephen Curry' "
        "AND season='2023-24' AND season_type='Regular Season'")
    assert len(rows) == 1
    games, ppg, total = rows[0]
    assert games > 0 and abs(total / games - ppg) < 0.06


def test_team_season_wins_losses_add_up(db):
    _, rows, _ = db.run_sql("SELECT games, wins + losses FROM team_season")
    assert rows and all(g == wl for g, wl in rows)


def test_coverage_mentions_all_seasons(db):
    assert "2021-22" in db.coverage() and "2025-26" in db.coverage()


@pytest.mark.parametrize("bad", [
    "DROP TABLE player_games",
    "DELETE FROM player_games",
    "SELECT 1; DROP TABLE teams",
    "COPY player_games TO '/tmp/x.csv'",
    "SELECT * FROM read_csv('/etc/passwd')",
    "SET enable_external_access = true",
    "ATTACH '/tmp/evil.db'",
])
def test_guard_blocks_unsafe_sql(db, bad):
    with pytest.raises(ValueError):
        db.run_sql(bad)


def test_cte_select_allowed_and_truncation(db):
    _, rows, truncated = db.run_sql("WITH x AS (SELECT * FROM player_games) SELECT * FROM x")
    assert len(rows) == 50 and truncated
    assert "truncated" in format_rows(["a"], [(1,)] * 50, True)


def test_sql_error_is_value_error(db):
    with pytest.raises(ValueError):
        db.run_sql("SELECT nonexistent_column FROM player_games")


def test_every_gold_query_executes(db):
    gold = [q for q in load_questions() if q["gold_sql"].strip()]
    assert len(gold) >= 25
    for q in gold:
        db.run_sql(q["gold_sql"])  # raises if the SQL is invalid against the schema


def test_unanswerable_questions_have_no_gold():
    assert sum(1 for q in load_questions() if q["category"] == "unanswerable" and not q["gold_sql"]) == 3


def test_numbers_in_handles_commas_and_percent():
    assert 2018.0 in numbers_in("He scored 2,018 points.") and 61.7 in numbers_in("TS% was 61.7%.")


def test_auto_grade():
    assert auto_grade([("Luka Dončić", 33.9)], "Luka Dončić led at 33.9 ppg.", False)
    assert auto_grade([(0.617,)], "His true shooting was 61.7%.", False)
    assert not auto_grade([("Luka Dončić", 33.9)], "Luka Dončić led at 31.0 ppg.", False)
    assert auto_grade([], "I don't have salary data.", True)
    assert not auto_grade([], "He earns $48 million.", True)
