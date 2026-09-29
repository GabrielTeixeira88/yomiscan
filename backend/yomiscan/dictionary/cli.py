import argparse
from pathlib import Path
import sys

from .importer import import_jmdict
from .models import DictionaryError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import official JMdict XML or XML.gz into SQLite")
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, default=Path("data/jmdict.sqlite3"))
    args = parser.parse_args(argv)
    try:
        count = import_jmdict(args.source, args.output)
    except DictionaryError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Imported {count:,} English JMdict entries into {args.output}")
    return 0
