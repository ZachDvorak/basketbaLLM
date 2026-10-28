"""Generate FAKE NBA-shaped CSVs for testing the pipeline without network access.

The numbers are random. Never use this data to judge the agent's real accuracy.
"""
import random
from pathlib import Path

import pandas as pd
from nba_api.stats.static import teams as static_teams

SEASONS = ["2021-22", "2022-23", "2023-24", "2024-25", "2025-26"]
STARS = ["Stephen Curry", "LeBron James", "Nikola Jokić", "Domantas Sabonis", "Jayson Tatum",
         "Luka Dončić", "Shai Gilgeous-Alexander", "Kevin Durant", "Devin Booker", "Joel Embiid",
         "Victor Wembanyama"]
TEAM_OF = {"Stephen Curry": "GSW", "LeBron James": "LAL", "Nikola Jokić": "DEN", "Domantas Sabonis": "SAC",
           "Jayson Tatum": "BOS", "Luka Dončić": "DAL", "Shai Gilgeous-Alexander": "OKC",
           "Kevin Durant": "PHX", "Devin Booker": "PHX", "Joel Embiid": "PHI", "Victor Wembanyama": "SAS"}


def make(out_dir, games_per_team=24, seed=7):
    rng = random.Random(seed)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    teams = static_teams.get_teams()
    by_abbr = {t["abbreviation"]: t for t in teams}

    roster, pid = {}, 1000
    for t in teams:
        names = [n for n, ab in TEAM_OF.items() if ab == t["abbreviation"]]
        names += [f"Player{pid + i} {t['nickname']}" for i in range(10 - len(names))]
        roster[t["abbreviation"]] = [(pid + i, n) for i, n in enumerate(names)]
        pid += 10

    team_rows, player_rows, gid = [], [], 20000000
    for season in SEASONS:
        for season_type, per_team in (("Regular Season", games_per_team), ("Playoffs", 6)):
            abbrs = list(by_abbr) if season_type == "Regular Season" else list(by_abbr)[:16]
            for g in range(per_team * len(abbrs) // 2):
                home, away = rng.sample(abbrs, 2)
                gid += 1
                date = f"{season[:4]}-{11 + g % 2}-{1 + g % 28:02d}"
                scores = {home: rng.randint(90, 130), away: rng.randint(90, 130)}
                for me, opp, at_home in ((home, away, True), (away, home, False)):
                    matchup = f"{me} vs. {opp}" if at_home else f"{me} @ {opp}"
                    t = by_abbr[me]
                    wl = "W" if scores[me] > scores[opp] else "L"
                    base = dict(season=season, season_type=season_type, season_id="22021", team_id=t["id"],
                                team_abbreviation=me, team_name=t["full_name"], game_id=gid, game_date=date,
                                matchup=matchup, wl=wl)
                    box = lambda pts, m: dict(min=m, fgm=pts // 3, fga=pts // 3 * 2 + 1, fg_pct=0.45, fg3m=pts // 9,
                                              fg3a=pts // 9 * 2 + 1, fg3_pct=0.35, ftm=pts // 6, fta=pts // 6 + 1,
                                              ft_pct=0.8, oreb=rng.randint(0, 3), dreb=rng.randint(0, 8),
                                              reb=rng.randint(0, 12), ast=rng.randint(0, 11), stl=rng.randint(0, 3),
                                              blk=rng.randint(0, 3), tov=rng.randint(0, 5), pf=rng.randint(0, 5),
                                              pts=pts, plus_minus=rng.randint(-20, 20))
                    team_rows.append({**base, **box(scores[me], 240), "player_id": None})
                    for pid_, name in roster[me]:
                        if name == "LeBron James" and rng.random() < 0.2:
                            continue  # LeBron sits out some games so the 'did not play' question has data
                        p = box(rng.randint(2, 42), rng.randint(10, 38))
                        player_rows.append({**base, "player_id": pid_, "player_name": name, "nickname": name,
                                            **p, "fantasy_pts": 0.0})

    pd.DataFrame(player_rows).to_csv(out_dir / "player_games.csv", index=False)
    pd.DataFrame(team_rows).drop(columns=["player_id"]).to_csv(out_dir / "team_games.csv", index=False)
    pd.DataFrame(teams).to_csv(out_dir / "teams.csv", index=False)
    return out_dir
