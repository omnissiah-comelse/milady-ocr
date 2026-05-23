"""Shared pytest fixtures.

The tests in this repo never hit OpenAI, Poppler, or real Mercalys PDFs:
- The vision call (`OcrWorker._vision_extract`) is monkeypatched per-test.
- The image-loading step (`OcrWorker._load_image_b64`) is short-circuited.
- A throwaway SQLite file is used for the DB.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Make `src/` importable as top-level modules (mirrors how Dockerfile runs).
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


@pytest.fixture
def tmp_db_path(tmp_path) -> str:
    return str(tmp_path / "ocr.db")


@pytest.fixture
def fake_pdf(tmp_path) -> Path:
    """A file with a .pdf extension; contents are never decoded because the
    vision/loader path is mocked away in tests."""
    p = tmp_path / "sample.pdf"
    p.write_bytes(b"%PDF-1.4 fake")
    return p
