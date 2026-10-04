"""Opt-in real-model evaluation; ordinary tests never download weights."""
from yomiscan.translation.benchmark import main

if __name__ == "__main__":
    raise SystemExit(main())
