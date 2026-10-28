# NBA / ABA / BAA data dictionary

Source: Kaggle `sumitrodatta/nba-aba-baa-stats` (Basketball-Reference data). Each CSV is loaded into DuckDB and
exposed through the views below. All data is **season-level**: there are no individual game logs.

## The most important conventions
- **`season` is the year the season ENDS.** 2023-24 is `season = 2024`; 1961-62 is `1962`. Every view also has
  `season_label` (`'2023-24'`). Show the label to users, filter on the number. Exception: `draft.draft_year` is the
  calendar year of the draft.
- **`lg`** is `NBA`, `ABA` (1968-1976) or `BAA` (1947-1949). The NBA starts in `season = 1950`. Filter `lg = 'NBA'`
  unless the user asks about the ABA/BAA; career totals should normally be NBA only (say so).
- **Player statistics are regular season only.** There are no playoff player stats, no game logs, no salaries, no
  injuries, no tracking or play-by-play data.
- **Traded players:** in a season a player was traded, the raw data has a combined row (team `2TM`, `3TM`, ...)
  plus one row per team. `player_season` keeps one row per player per season (the combined row), so it is safe to
  rank and to sum across seasons. `player_season_team` has every row, for "what did he do with team X" questions.
  Never add up `player_season_team` rows across a whole season.
- **Names:** different players can share a name, so group by `player_id`. Names carry accents (Jokić, Dončić): use
  `strip_accents(player) ILIKE '%jokic%'` or the exact spelling.
- **NULL means "not recorded", not zero.** Steals, blocks, offensive rebounds: from 1973-74. Turnovers: from
  1977-78. Three-point stats: from 1979-80. Usage rate: from 1977-78. BPM and VORP: from 1973-74. Minutes: from 1951-52.
- **Percentages are fractions** (0.452 = 45.2%), except the advanced "percent" stats (`usg_pct`, `ast_pct`,
  `reb_pct`, `stl_pct`, `blk_pct`, `tov_pct`), which are already on a 0-100 scale.
- **Team abbreviations follow Basketball-Reference**: BRK (Nets), CHO (Hornets since 2015), PHO (Suns), etc., and
  historical ones (SEA, NJN, NOH, VAN). Use `team_abbrev` to translate to names.

## Views

### player_season (one row per player per season) and player_season_team (one row per player per season per team)
Identity: season, season_label, lg, player_id, player, age, team, pos, g (games played), gs (games started).
Per game: mpg, ppg, rpg, orpg, drpg, apg, spg, bpg, tpg, pfpg, fgm_pg, fga_pg, fg3m_pg, fg3a_pg, ftm_pg, fta_pg.
Shooting: fg_pct, fg3_pct, ft_pct, efg_pct, ts_pct (true shooting).
Season totals: total_min, total_pts, total_reb, total_ast, total_stl, total_blk, total_tov, fgm, fga, fg3m, fg3a, ftm,
fta, triple_doubles.
Advanced: per, usg_pct, ast_pct, reb_pct, stl_pct, blk_pct, tov_pct, ows, dws, ws (win shares), ws_48, obpm, dbpm,
bpm, vorp.

### team_season (one row per team per season)
season, season_label, lg, team_name, team_abbrev, made_playoffs (TRUE if the team made that year's playoffs;
**not** playoff statistics), games, wins, losses, win_pct, pythag_wins, pythag_losses, ppg, opp_ppg (points
allowed per game), margin (average point margin), sos, srs (simple rating system), o_rtg, d_rtg, n_rtg (points per
100 possessions), pace, ts_pct, efg_pct, tov_pct, orb_pct, drb_pct, fg3a_rate, ft_rate, avg_age, fg_pct, fg3m_pg,
fg3_pct, rpg, apg, spg, bpg, tpg, arena, attendance, attendance_per_game. Rating and pace columns start in the 1950s.

### league_season (one row per league per season)
season, season_label, lg, ppg_per_team, pace, off_rating, ts_pct, efg_pct, fg3a_rate, ft_rate, fg3m_pg_per_team,
fg_pct, avg_age. Use for comparing eras.

### awards
season, season_label, award, player, player_id, age, first_place_votes, pts_won, pts_max, share (vote share),
winner (TRUE for the winner). `award` values: `nba mvp`, `nba roy`, `nba dpoy`, `nba mip`, `nba smoy`,
`nba clutch_poy`, `aba mvp`, `aba roy`, `baa roy`. (Finals MVP is not in this data.)

### all_star
season, season_label, lg, player, player_id, all_star_team, replaced (TRUE if an injury replacement).

### all_league_teams
season, season_label, lg, team_type (`All-NBA`, `All-Defense`, `All-Rookie`, `All-ABA`, `All-BAA`),
team_number (`1st`, `2nd`, `3rd`), player, player_id, position.

### draft
draft_year, lg, overall_pick, round, team, player, player_id, college (NULL for players with no US college).

### players (one row per player, career info)
player_id, player, pos, height_in, weight_lb, birth_date, colleges, first_season, last_season (end-year convention),
debut, hall_of_famer.

### team_abbrev
season, lg, team_name, abbreviation, made_playoffs.

## Query tips
- Leaderboards need a minimum-games filter (`g >= 50` is a reasonable default for per-game stats) or a minimum
  minutes filter for advanced stats (`total_min >= 1000`); otherwise a player with 2 games tops every list.
- Do not round before sorting: ties after rounding hide the real leader. Round only the displayed value.
- Career total = `sum(total_pts)` over `player_season` for one `player_id`. Career per-game average = total divided
  by `sum(g)`, not the average of the yearly averages.
- "Last season" means the most recent season in the data (`max(season)`), not the current calendar year.
