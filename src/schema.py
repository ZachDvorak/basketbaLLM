"""Column names every game-level table must provide. Shared by pull_data.py and prepare_data.py."""

BOX_STATS = {
    "game_id", "game_date", "matchup", "wl", "min", "fgm", "fga", "fg3m", "fg3a",
    "ftm", "fta", "oreb", "dreb", "reb", "ast", "stl", "blk", "tov", "pf", "pts",
    "plus_minus", "team_id", "team_abbreviation",
}
REQUIRED_COLS = {
    "player_games": BOX_STATS | {"player_id", "player_name"},
    "team_games": BOX_STATS | {"team_name"},
}

# Used by prepare_data.py for datasets that are not from nba_api.
# HARD: the agent's views cannot work without these. SOFT: filled with NULL (or a fallback) and reported.
STAT_COLS = ["min", "fgm", "fga", "fg3m", "fg3a", "ftm", "fta", "oreb", "dreb", "reb", "ast", "stl", "blk",
             "tov", "pf", "pts", "plus_minus"]
HARD = {"season", "season_type", "player_id", "player_name", "team_abbreviation", "game_id", "game_date", "wl",
        "min", "fgm", "fga", "fg3m", "fg3a", "ftm", "fta", "reb", "ast", "stl", "blk", "tov", "pts"}
SOFT = {"oreb", "dreb", "pf", "plus_minus", "matchup", "team_id", "team_name"}
