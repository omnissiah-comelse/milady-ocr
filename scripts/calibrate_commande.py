"""Calibration harness for `doc_type=commande` OCR — pending real samples.

COM-606 QA blocker #3: calibration on 20-50 anonymized Mercalys order PDFs.
This repo intentionally does NOT carry the PDFs or any client document. Run
this script locally against a directory of anonymized samples to compare
GPT-4o-mini Vision extractions to hand-curated ground-truth JSON files.

Layout expected at the path you pass in:

    samples/
      order-001.pdf
      order-001.expected.json   # subset of CommandeOcrResult fields to assert
      order-002.pdf
      order-002.expected.json
      ...

`order-001.expected.json` only needs the fields you care about — e.g.:

    {
      "supplier_name": "BOULANGERIE DURAND",
      "num_cmd": "CMD-2026-42",
      "date_cmd": "2026-05-02",
      "total_ht": 250.0
    }

The script reports per-field accuracy and a confusion list of mismatches so
the prompt / threshold can be tuned. Until 20-50 anonymized PDFs are
assembled and dropped in `samples/`, calibration is PENDING and no accuracy
numbers should be quoted to QA.

Usage:
    OPENAI_API_KEY=... PYTHONPATH=src python3 scripts/calibrate_commande.py samples/
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


TRACKED_FIELDS = ("supplier_name", "num_cmd", "num_bl", "date_cmd", "total_ht")


def _load_expected(p: Path) -> dict:
    if not p.exists():
        return {}
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: calibrate_commande.py <samples_dir>", file=sys.stderr)
        return 2

    samples = Path(argv[1])
    if not samples.is_dir():
        print(f"error: not a directory: {samples}", file=sys.stderr)
        return 2

    pdfs = sorted(samples.glob("*.pdf"))
    if not pdfs:
        print(
            "No PDFs found. Calibration is PENDING anonymized Mercalys samples — "
            "see README 'Calibration limitation (COM-606)'.",
            file=sys.stderr,
        )
        return 1

    # Lazy import: keeps the script useful as documentation even when the
    # OCR deps (openai, pdf2image) are not installed locally.
    from ocr import OcrWorker  # noqa: WPS433

    worker = OcrWorker(api_key=os.environ.get("OPENAI_API_KEY", ""))

    totals = {f: {"checked": 0, "ok": 0} for f in TRACKED_FIELDS}
    mismatches: list[str] = []

    for pdf in pdfs:
        expected = _load_expected(pdf.with_suffix(".expected.json"))
        result = worker.process_commande(str(pdf), supplier_candidates=[])
        actual = result.model_dump()
        for field in TRACKED_FIELDS:
            if field not in expected:
                continue
            totals[field]["checked"] += 1
            if expected[field] == actual.get(field):
                totals[field]["ok"] += 1
            else:
                mismatches.append(
                    f"{pdf.name} {field}: expected={expected[field]!r} actual={actual.get(field)!r}"
                )

    print("Field accuracy:")
    for field, counts in totals.items():
        n = counts["checked"]
        ok = counts["ok"]
        pct = (ok / n * 100) if n else 0.0
        print(f"  {field:14s} {ok}/{n} ({pct:5.1f}%)")
    if mismatches:
        print("\nMismatches:")
        for m in mismatches:
            print(f"  - {m}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
