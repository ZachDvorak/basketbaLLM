"""Which CSV files the agent needs and which columns it reads from each.

Source dataset: Kaggle `sumitrodatta/nba-aba-baa-stats` (Basketball-Reference data, one CSV per table).
db.py validates your files against this list and tells you exactly what is missing.
"""

# table name -> (CSV file name, columns the views read)
FILES = {
    "player_per_game": ("Player Per Game.csv", [
        "season", "lg", "player", "player_id", "age", "team", "pos", "g", "gs", "mp_per_game", "fg_per_game",
        "fga_per_game", "fg_percent", "x3p_per_game", "x3pa_per_game", "x3p_percent", "ft_per_game",
        "fta_per_game", "ft_percent", "e_fg_percent", "orb_per_game", "drb_per_game", "trb_per_game",
        "ast_per_game", "stl_per_game", "blk_per_game", "tov_per_game", "pf_per_game", "pts_per_game"]),
    "player_totals": ("Player Totals.csv", [
        "season", "lg", "player_id", "team", "mp", "fg", "fga", "x3p", "x3pa", "ft", "fta", "orb", "drb",
        "trb", "ast", "stl", "blk", "tov", "pf", "pts", "trp_dbl"]),
    "advanced": ("Advanced.csv", [
        "season", "lg", "player_id", "team", "per", "ts_percent", "usg_percent", "ast_percent", "trb_percent",
        "stl_percent", "blk_percent", "tov_percent", "ows", "dws", "ws", "ws_48", "obpm", "dbpm", "bpm", "vorp"]),
    "team_summaries": ("Team Summaries.csv", [
        "season", "lg", "team", "abbreviation", "playoffs", "age", "w", "l", "pw", "pl", "mov", "sos", "srs",
        "o_rtg", "d_rtg", "n_rtg", "pace", "ts_percent", "e_fg_percent", "tov_percent", "orb_percent",
        "drb_percent", "x3p_ar", "f_tr", "arena", "attend", "attend_g"]),
    "team_stats_per_game": ("Team Stats Per Game.csv", [
        "season", "lg", "team", "g", "pts_per_game", "fg_percent", "x3p_per_game", "x3p_percent",
        "trb_per_game", "ast_per_game", "stl_per_game", "blk_per_game", "tov_per_game"]),
    "opponent_stats_per_game": ("Opponent Stats Per Game.csv", ["season", "lg", "team", "opp_pts_per_game"]),
    "awards": ("Player Award Shares.csv", [
        "season", "award", "player", "player_id", "age", "first", "pts_won", "pts_max", "share", "winner"]),
    "all_star": ("All-Star Selections.csv", ["player", "player_id", "team", "season", "lg", "replaced"]),
    "all_league": ("End of Season Teams.csv", [
        "season", "lg", "type", "number_tm", "player", "player_id", "position"]),
    "draft": ("Draft Pick History.csv", [
        "season", "lg", "overall_pick", "round", "tm", "player", "player_id", "college"]),
    "players": ("Player Career Info.csv", [
        "player", "player_id", "pos", "ht_in_in", "wt", "birth_date", "colleges", "from", "to", "debut", "hof"]),
    "team_abbrev": ("Team Abbrev.csv", ["season", "lg", "team", "abbreviation", "playoffs"]),
}
