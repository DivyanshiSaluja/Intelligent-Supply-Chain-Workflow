"""Build the real-demand dataset from UCI Online Retail II.

    python scripts/prepare_real_data.py

If data/real/online_retail_ii_daily_top30.csv is present (it is committed), nothing is
downloaded. To rebuild it from the raw file, download
https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip
to data/external/online_retail_ii/online_retail_ii.zip and delete the CSV (takes a few minutes).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from supplygen.realdata import REAL_DB, generate_real

if __name__ == "__main__":
    print(f"Writing {REAL_DB}")
    for k, v in generate_real().items():
        print(f"  {k:26s} {v}")
