"""Stage 2 spike: score JS/browser OCR runs against the reference arm with the project's metrics (G1, G2).

    uv run --frozen python research/stage-2/score_ocr.py reports/stage2-ocr-reference.json RUN.json [RUN.json ...]

RUN.json is a node-*.json from validate-node.mjs or a browser report from run-browser.mjs
(each run's rows carry id, split, reference and output). Prints aggregate figures only.
"""

import json
import re
import sys
from pathlib import Path

from yomiscan.vision_benchmark.metrics import transcription_metrics
from yomiscan.vision_benchmark.runner import normalize_reference
from yomiscan.vision_benchmark.summary import accuracy

JAPANESE = re.compile(r"[぀-ヿ㐀-鿿ｦ-ﾟ]")


def failed(text: str) -> bool:
    return not text or not JAPANESE.search(text)


def score(reference_rows: dict[str, dict], rows: list[dict]) -> dict:
    out = {}
    for name, selected in (("all", rows), ("held_out", [r for r in rows if r["split"] == "held_out"])):
        metrics = [{"normalized": transcription_metrics(normalize_reference(r["reference"]) if r["reference"] is not None else None,
                                                        normalize_reference(r["output"]))} for r in selected]
        reference = [reference_rows[r["id"]] for r in selected]
        out[name] = {"browser": accuracy(metrics, "normalized")["cer"], "reference": accuracy(reference, "normalized")["cer"]}
    # G2: new total failures where the reference arm succeeded (empty / non-Japanese / truncated).
    new_failures = 0
    for r in rows:
        ref_output = reference_rows[r["id"]]["output"]
        truncated = len(normalize_reference(r["output"])) < 0.5 * len(normalize_reference(ref_output))
        if not failed(ref_output) and (failed(r["output"]) or truncated):
            new_failures += 1
    out["new_failures"] = new_failures
    out["blocks"] = len(rows)
    out["identical_to_reference"] = sum(r["output"] == reference_rows[r["id"]]["output"] for r in rows)
    return out


def main() -> None:
    reference = {row["id"]: row for row in json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["rows"]}
    for path in sys.argv[2:]:
        report = json.loads(Path(path).read_text(encoding="utf-8"))
        runs = report["runs"] if "runs" in report else [report]
        for run in runs:
            if "rows" not in run:
                continue
            label = run.get("config") or {"variant": run.get("variant"), "decoding": run.get("decoding"), "backend": run.get("backend")}
            s = score(reference, run["rows"])
            delta = 100 * (s["all"]["browser"] - s["all"]["reference"])
            held = 100 * (s["held_out"]["browser"] - s["held_out"]["reference"])
            print(f"{Path(path).name} {'/'.join(str(v) for v in label.values())}: CER {100 * s['all']['browser']:.2f}% "
                  f"(reference {100 * s['all']['reference']:.2f}%, delta {delta:+.2f} pp; held-out delta {held:+.2f} pp) "
                  f"new failures {s['new_failures']}/{s['blocks']} ({100 * s['new_failures'] / s['blocks']:.1f}%) "
                  f"identical {s['identical_to_reference']}/{s['blocks']}")


if __name__ == "__main__":
    main()
