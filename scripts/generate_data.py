"""Generate the synthetic dataset (SQLite + CSV exports).

    python scripts/generate_data.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from supplygen.config import DB_PATH
from supplygen.datagen import generate

if __name__ == "__main__":
    print(f"Writing {DB_PATH}")
    for k, v in generate().items():
        print(f"  {k:16s} {v}")
    print("CSV copies are in data/csv/")
