# NBA data dictionary

Source: `nba_api` (`LeagueGameLog` endpoint). Every table is loaded into DuckDB from `data/*.csv`.
Box-score stats are per game unless a column name says otherwise.

## Conventions
- `season` is text like `2024-25`. `season_type` is `Regular Season` or `Playoffs`. **Always filter `season_type`.**
- `game_date` is `YYYY-MM-DD`. `game_id` is shared by the two teams (and all players) in a game.
- `matchup`: `BOS vs. NYK` means BOS played at home; `BOS @ NYK` means BOS played away.
- `wl` is `W` or `L` for the row's team. `min` is minutes played.
- A player traded mid-season has several `team_abbreviation` values; the season views combine them.
- Not in this data: salaries, injuries, play-by-play, tracking, advanced defensive metrics, draft info.

## Tables (one row per ...)

### player_games (player per game)
season, season_type, season_id, player_id, player_name, team_id, team_abbreviation, team_name,
game_id, game_date, matchup, wl, min, fgm, fga, fg_pct, fg3m, fg3a, fg3_pct, ftm, fta, ft_pct,
oreb, dreb, reb, ast, stl, blk, tov, pf, pts, plus_minus, fantasy_pts

### team_games (team per game)
Same box-score columns as player_games but for the whole team: season, season_type, team_id,
team_abbreviation, team_name, game_id, game_date, matchup, wl, min, fgm ... pts, plus_minus.

### teams (team)
id, full_name, abbreviation, nickname, city, state, year_founded

### players (player directory, optional)
person_id, display_first_last, rosterstatus, from_year, to_year, team_id, team_abbreviation, ...

## Views (pre-aggregated, prefer these for season questions)

### player_season (player per season per season_type)
player_id, player_name, season, season_type, teams, games, mpg, total_pts, ppg, total_reb, rpg,
total_ast, apg, spg, bpg, tpg, fgm, fga, fg_pct, fg3m, fg3a, fg3_pct, ftm, fta, ft_pct,
ts_pct (true shooting = pts / (2 * (fga + 0.44 * fta))), avg_plus_minus.
Percentages are fractions (0.452 = 45.2%).

### team_season (team per season per season_type)
team_id, team_name, team_abbreviation, season, season_type, games, wins, losses, win_pct, ppg,
opp_ppg (points allowed per game), avg_margin (ppg - opp_ppg), fg3m_pg, fg3_pct, rpg, apg, tpg.

## Gotchas for query writing
- Leaderboards need a minimum-games filter (`games >= 40` is a reasonable default), otherwise a
  player with 2 games tops every percentage list.
- "Last season" means the most recent complete season in the data, not the calendar year.
- Per-game averages in `player_season` are the mean over games played, not over team games.
- Back-to-backs, home/away splits, and win/loss splits come from `player_games` / `team_games`.
