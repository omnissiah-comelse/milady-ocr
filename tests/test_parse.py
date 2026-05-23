"""Pure-Python parser tests — no FastAPI, no IO, no network."""
from __future__ import annotations

from ocr import OcrWorker
from models import DocumentType, SupplierCandidate


FACTURE_PAYLOAD = {
    "supplier_name": "ACME SARL",
    "num_fact": "F-2026-001",
    "date_fact": "2026-04-12",
    "total_ht": 100.0,
    "total_ttc": 120.0,
    "tva_rate": 20.0,
    "line_items": [
        {"description": "Widget", "qty": 2, "unit_price": 30.0, "total_ht": 60.0},
        {"description": "Gadget", "qty": 1, "unit_price": 40.0, "total_ht": 40.0},
    ],
    "raw_text": "ACME SARL ...",
    "confidence": 0.93,
    "field_confidence": {"num_fact": 0.95, "total_ht": 0.9},
    "warnings": [],
}


COMMANDE_PAYLOAD = {
    "supplier_name": "BOULANGERIE DURAND",
    "num_cmd": "CMD-2026-42",
    "num_bl": "BL-9001",
    "date_cmd": "2026-05-02",
    "total_ht": 250.0,
    "line_items": [
        {
            "description": "Farine T65 25kg",
            "qty": 4,
            "unit_price": 25.0,
            "total_ht": 100.0,
            "cost_center_label": "BOULANGERIE",
            "cost_center_code": "BOUL",
        },
        {
            "description": "Levure fraiche 500g",
            "qty": 10,
            "unit_price": 15.0,
            "total_ht": 150.0,
            "cost_center_label": "BOULANGERIE",
            "cost_center_code": "BOUL",
        },
    ],
    "raw_text": "BON DE COMMANDE ...",
    "confidence": 0.88,
    "field_confidence": {"num_cmd": 0.94, "date_cmd": 0.9, "total_ht": 0.85},
    "warnings": [],
}


def test_parse_facture_basic():
    result = OcrWorker.parse_facture(FACTURE_PAYLOAD, supplier_candidates=[])
    assert result.num_fact == "F-2026-001"
    assert result.date_fact == "2026-04-12"
    assert result.total_ht == 100.0
    assert result.total_ttc == 120.0
    assert result.tva_rate == 20.0
    assert len(result.line_items) == 2
    assert result.line_items[0].description == "Widget"
    assert result.confidence == 0.93
    assert result.field_confidence == {"num_fact": 0.95, "total_ht": 0.9}
    assert result.warnings == []


def test_parse_commande_basic():
    result = OcrWorker.parse_commande(COMMANDE_PAYLOAD, supplier_candidates=[])
    assert result.num_cmd == "CMD-2026-42"
    assert result.num_bl == "BL-9001"
    assert result.date_cmd == "2026-05-02"
    assert result.total_ht == 250.0
    assert len(result.line_items) == 2
    li = result.line_items[0]
    assert li.description == "Farine T65 25kg"
    assert li.cost_center_label == "BOULANGERIE"
    assert li.cost_center_code == "BOUL"
    assert result.field_confidence["num_cmd"] == 0.94
    assert result.warnings == []


def test_amount_mismatch_warning_facture():
    payload = dict(FACTURE_PAYLOAD)
    payload["total_ht"] = 500.0  # line_items sum is 100; way off
    result = OcrWorker.parse_facture(payload, supplier_candidates=[])
    assert any("does not match" in w for w in result.warnings)


def test_amount_mismatch_warning_commande():
    payload = dict(COMMANDE_PAYLOAD)
    payload["total_ht"] = 999.0  # line_items sum is 250
    result = OcrWorker.parse_commande(payload, supplier_candidates=[])
    assert any("does not match" in w for w in result.warnings)


def test_amount_within_tolerance_no_warning_commande():
    # 250.001 vs 250.0 — within the 1 cent absolute tolerance.
    payload = dict(COMMANDE_PAYLOAD)
    payload["total_ht"] = 250.001
    result = OcrWorker.parse_commande(payload, supplier_candidates=[])
    assert not any("does not match" in w for w in result.warnings)


def test_supplier_match_typed_candidate_commande():
    candidates = [
        SupplierCandidate(id_f=17, name="Boulangerie Durand"),
        SupplierCandidate(id_f=23, name="Grossiste Martin"),
    ]
    result = OcrWorker.parse_commande(COMMANDE_PAYLOAD, supplier_candidates=candidates)
    assert result.supplier_match.id_f == 17
    assert result.supplier_match.name == "Boulangerie Durand"
    assert result.supplier_match.score is not None and result.supplier_match.score > 0.6


def test_supplier_unmatched_emits_warning_commande():
    candidates = [SupplierCandidate(id_f=99, name="Quelque chose de totalement different")]
    result = OcrWorker.parse_commande(COMMANDE_PAYLOAD, supplier_candidates=candidates)
    assert result.supplier_match.id_f is None
    assert any("No supplier match" in w for w in result.warnings)


def test_supplier_match_legacy_list_str_facture():
    # Backward compat: list[str] still works and id_f maps to 1-based index.
    result = OcrWorker.parse_facture(
        FACTURE_PAYLOAD,
        supplier_candidates=[
            type("S", (), {"id_f": 1, "name": "ACME SARL"})()  # behave like SupplierCandidate
        ],
    )
    # Use the real worker normalization through process_file would be ideal,
    # but parse_facture takes already-typed candidates. Test the legacy path
    # via the normalizer directly:
    from ocr import _normalize_supplier_candidates
    normalized = _normalize_supplier_candidates(["ACME SARL", "Other"])
    assert normalized[0].id_f == 1
    assert normalized[1].id_f == 2
    assert normalized[0].name == "ACME SARL"


def test_doc_type_dispatch(monkeypatch, fake_pdf):
    """process_file routes by doc_type."""
    worker = OcrWorker(api_key="test", model="x")

    # Bypass image loading.
    monkeypatch.setattr(worker, "_load_image_b64", lambda p: "FAKEB64")

    seen = {}

    def fake_vision(b64, system_prompt, user_text):
        seen["system_prompt"] = system_prompt
        if "commande" in system_prompt.lower() or "order" in system_prompt.lower():
            return COMMANDE_PAYLOAD
        return FACTURE_PAYLOAD

    monkeypatch.setattr(worker, "_vision_extract", fake_vision)

    facture = worker.process_file(str(fake_pdf), [], doc_type=DocumentType.FACTURE)
    assert facture.num_fact == "F-2026-001"

    commande = worker.process_file(str(fake_pdf), [], doc_type=DocumentType.COMMANDE)
    assert commande.num_cmd == "CMD-2026-42"
