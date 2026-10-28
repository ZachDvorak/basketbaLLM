"""Look inside a downloaded dataset: every CSV, its columns, and sample rows.

    python src/inspect_csvs.py /content/my-kaggle-folder

Also tells you which of the files the agent expects are present. Use this if `check_data.py` reports missing
files or columns, or to paste into a chat when asking for help.
"""
import sys
from pathlib import Path

import duckdb

from schema import FILES


def main(folder):
    files = sorted(Path(folder).rglob("*.csv"))
    if not files:
        sys.exit(f"No .csv files found under {folder}")
    found = {p.name.lower() for p in files}
    print("Files the agent expects:")
    for table, (filename, _) in FILES.items():
        print(f"  [{'ok' if filename.lower() in found else 'MISSING'}] {filename}")
    for path in files:
        con = duckdb.connect()
        src = f"read_csv_auto('{path}', nullstr='NA', sample_size=20000, ignore_errors=true)"
        rows = con.execute(f"SELECT count(*) FROM {src}").fetchone()[0]
        cols = con.execute(f"DESCRIBE SELECT * FROM {src}").fetchall()
        print(f"\n=== {path.relative_to(folder)}  ({rows:,} rows, {len(cols)} columns)")
        print("  " + ", ".join(f"{c[0]} [{c[1]}]" for c in cols))
        for row in con.execute(f"SELECT * FROM {src} LIMIT 3").fetchall():
            print("   ", row)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
