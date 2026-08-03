"""Genera il report del campione revisionato senza invocare provider o pubblicare."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from neveran_gazzetta.evaluation import (  # noqa: E402
    EvaluationReview,
    build_evaluation_report,
    load_scenarios,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("reviews", type=Path, help="File JSON contenente una lista di review")
    parser.add_argument("--dataset", type=Path, default=ROOT / "eval" / "scenarios.yaml")
    args = parser.parse_args()
    raw = json.loads(args.reviews.read_text(encoding="utf-8"))
    reviews = tuple(EvaluationReview.model_validate(item) for item in raw)
    report = build_evaluation_report(load_scenarios(args.dataset), reviews)
    print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
