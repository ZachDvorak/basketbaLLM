"""Look inside a downloaded dataset so you can map its columns to the agent's tables.

    python src/inspect_csvs.py /content/my-kaggle-folder

Prints, for every CSV: row count, columns with types, and 3 sample rows. Then it lists which of the columns
the agent needs look present or missing. Copy the output into the chat if you want help writing the mapping.
"""
import sys
from pathlib import Path

import duckdb

from schema import HARD, SOFT, STAT_COLS


def main(folder):
    files = sorted(Path(folder).rglob("*.csv"))
    if not files:
        sys.exit(f"No .csv files found under {folder}")
    wanted = HARD | SOFT | set(STAT_COLS)
    for path in files:
        rel = path.relative_to(folder)
        con = duckdb.connect()
        rel_sql = f"read_csv_auto('{path}', sample_size=20000, ignore_errors=true)"
        rows = con.execute(f"SELECT count(*) FROM {rel_sql}").fetchone()[0]
        cols = con.execute(f"DESCRIBE SELECT * FROM {rel_sql}").fetchall()
        print(f"\n=== {rel}  ({rows:,} rows, {len(cols)} columns)")
        print("  " + ", ".join(f"{c[0]} [{c[1]}]" for c in cols))
        sample = con.execute(f"SELECT * FROM {rel_sql} LIMIT 3").fetchall()
        for row in sample:
            print("   ", row)
        exact = sorted(wanted & {c[0].lower() for c in cols})
        print(f"  columns already matching the agent's names: {exact or 'none'}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
