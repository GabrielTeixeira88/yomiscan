"""Summarize a manually completed benchmark ratings CSV; never selects a winner."""
import argparse
import json
from yomiscan.translation.benchmark import summarize_ratings
from pathlib import Path

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ratings", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(summarize_ratings(args.ratings), indent=2))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
