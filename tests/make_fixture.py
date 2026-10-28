"""Write a tiny FAKE dataset in the same file layout as the Kaggle one, for tests that need no downloads.

It includes the awkward cases on purpose: a traded player (combined 2TM row + per-team rows), 'NA' values, a
'League Average' team row, and an old-era player with missing steals/blocks. The numbers are made up.
"""
from pathlib import Path

import pandas as pd

from schema import FILES


def _frame(table, rows):
    """Rows are dicts; every required column not given becomes 1 (numbers) so the views have something to read."""
    columns = FILES[table][1]
    return pd.DataFrame([{c: r.get(c, 1) for c in columns} for r in rows], columns=columns)


def make(out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    def keys(season, lg, player, pid, team, age=25, pos="PG"):
        return dict(season=season, lg=lg, player=player, player_id=pid, team=team, age=age, pos=pos)

    stints = [
        dict(**keys(2024, "NBA", "Luka Dončić", "doncilu01", "DAL"), g=70, pts_per_game=33.9, pts=2370, mp=2500, trp_dbl=10),
        dict(**keys(2025, "NBA", "Luka Dončić", "doncilu01", "LAL"), g=50, pts_per_game=28.2, pts=1410, mp=1700, trp_dbl=4),
        dict(**keys(2022, "NBA", "James Harden", "hardeja01", "2TM", 32, "SG"), g=65, pts_per_game=22.0, pts=1430, mp=2300),
        dict(**keys(2022, "NBA", "James Harden", "hardeja01", "BRK", 32, "SG"), g=44, pts_per_game=22.5, pts=990, mp=1500),
        dict(**keys(2022, "NBA", "James Harden", "hardeja01", "PHI", 32, "SG"), g=21, pts_per_game=21.0, pts=441, mp=800),
        dict(**keys(1970, "NBA", "Old Timer", "timerol01", "BOS", 30, "C"), g=80, pts_per_game=12.0, pts=960, mp=2000,
             stl_per_game="NA", blk_per_game="NA", total_stl="NA", total_blk="NA"),
        dict(**keys(1970, "ABA", "Old Timer", "timerol02", "DEN", 30, "C"), g=60, pts_per_game=20.0, pts=1200, mp=1800),
    ]
    pg = _frame("player_per_game", [{**s, "stl_per_game": s.get("stl_per_game", 1.0), "blk_per_game": s.get("blk_per_game", 1.0)} for s in stints])
    pt = _frame("player_totals", [{**s, "stl": s.get("total_stl", 50), "blk": s.get("total_blk", 20)} for s in stints])
    adv = _frame("advanced", [dict(season=s["season"], lg=s["lg"], player_id=s["player_id"], team=s["team"],
                                   per=20.0, bpm=("NA" if s["season"] == 1970 else 5.0)) for s in stints])
    teams = [
        dict(season=2024, lg="NBA", team="Dallas Mavericks", abbreviation="DAL", playoffs=True, w=50, l=32, mov=2.1, pace=99.0),
        dict(season=2024, lg="NBA", team="Boston Celtics", abbreviation="BOS", playoffs=True, w=64, l=18, mov=11.3, pace=98.0),
        dict(season=2024, lg="NBA", team="League Average", abbreviation="NA", playoffs=False, w="NA", l="NA", mov=0.0, pace=98.5),
        dict(season=1970, lg="ABA", team="Denver Rockets", abbreviation="DEN", playoffs=False, w=40, l=44, mov=-1.0, pace="NA"),
    ]
    summaries = _frame("team_summaries", [{**t, "arena": "Arena", "attend": 1000, "attend_g": 25} for t in teams])
    per_game = _frame("team_stats_per_game", [dict(season=t["season"], lg=t["lg"], team=t["team"], g=82,
                                                   pts_per_game=115.0 if t["team"] != "League Average" else 114.2) for t in teams])
    opp = _frame("opponent_stats_per_game", [dict(season=t["season"], lg=t["lg"], team=t["team"], opp_pts_per_game=110.0)
                                             for t in teams if t["team"] != "League Average"])
    awards = _frame("awards", [
        dict(season=2024, award="nba mvp", player="Nikola Jokić", player_id="jokicni01", winner=True),
        dict(season=2024, award="nba mvp", player="Luka Dončić", player_id="doncilu01", winner=False)])
    all_star = _frame("all_star", [dict(player="Luka Dončić", player_id="doncilu01", team="West", season=2024, lg="NBA", replaced=False)])
    all_league = _frame("all_league", [dict(season=2024, lg="NBA", type="All-NBA", number_tm="1st", player="Luka Dončić",
                                            player_id="doncilu01", position="G")])
    draft = _frame("draft", [dict(season=2018, lg="NBA", overall_pick=3, round=1, tm="DAL", player="Luka Dončić",
                                  player_id="doncilu01", college="NA")])
    players = _frame("players", [dict(player="Luka Dončić", player_id="doncilu01", pos="G", ht_in_in=79, wt=230,
                                      birth_date="1999-02-28", colleges="NA", **{"from": 2019, "to": 2025},
                                      debut="2018-10-17T00:00:00Z", hof=False)])
    abbrev = _frame("team_abbrev", [dict(season=t["season"], lg=t["lg"], team=t["team"], abbreviation=t["abbreviation"],
                                         playoffs=t["playoffs"]) for t in teams])

    tables = dict(player_per_game=pg, player_totals=pt, advanced=adv, team_summaries=summaries,
                  team_stats_per_game=per_game, opponent_stats_per_game=opp, awards=awards, all_star=all_star,
                  all_league=all_league, draft=draft, players=players, team_abbrev=abbrev)
    for table, frame in tables.items():
        frame.to_csv(out_dir / FILES[table][0], index=False, na_rep="NA")
    return out_dir
