# Milady OCR

Invoice **and order (commande)** OCR sidecar for Milady. Runs on a small VPS.

## What It Does

1. Receives PDFs/images via upload or email forwarding
2. Runs OCR (GPT-4o-mini Vision) to extract structured data
3. Fuzzy-matches supplier against Milady's fournisseurs table (scoped per PDV)
4. Queues results for review or auto-insertion
5. Milady long-polls `/jobs/pending?id_pdv=X` to fetch completed OCR jobs

Two document types are supported (COM-606):

- `facture` — invoice (default; pre-existing behavior, preserved)
- `commande` — Mercalys order export PDF; extracts `num_cmd`, `num_bl`, `date_cmd`, `total_ht`, line items with cost-center hints

## Stack

- Python 3.11 + FastAPI
- SQLite (queue storage)
- pdf2image + Pillow (PDF→image conversion)
- OpenAI GPT-4o-mini Vision (OCR)
- TheFuzz (supplier fuzzy matching)
- Docker + docker-compose

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | /upload | Upload PDF/image. Accepts `doc_type=facture\|commande` (default `facture`). Returns `job_id`. |
| GET | /jobs/{job_id} | Check OCR status + result |
| GET | /jobs/pending | Long-poll for pending jobs by PDV |
| POST | /webhook/email | Receive forwarded invoice/order emails |
| GET | /health | Health check |

### `POST /upload`

Query params:
- `id_pdv` (int, required) — Milady PDV id
- `doc_type` (`facture` | `commande`, optional, default `facture`)

The response includes `doc_type` so the caller can confirm what was queued.

### `GET /jobs/{job_id}` result shapes

For `doc_type=facture` (legacy/default), `job.ocr_result` is populated with the invoice fields (`num_fact`, `date_fact`, `total_ht`, `total_ttc`, `tva_rate`, `line_items[]`, etc.). `commande_result` is `null`.

For `doc_type=commande`, `job.commande_result` is populated and `ocr_result` is `null`. Shape:

```json
{
  "supplier_name": "BOULANGERIE DURAND",
  "supplier_match": {"id_f": 17, "name": "Boulangerie Durand", "score": 0.91},
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
      "cost_center_code": "BOUL"
    }
  ],
  "raw_text": "...",
  "confidence": 0.88,
  "field_confidence": {"num_cmd": 0.94, "date_cmd": 0.9, "total_ht": 0.85},
  "warnings": []
}
```

Warnings include:
- `"total_ht (X) does not match sum of line items (Y)"` — emitted when the extracted header total does not reconcile with the sum of line item totals beyond a 1 cent absolute / 0.5% relative tolerance.
- `"No supplier match (best='X' score=N) for 'Y'"` — emitted when no fournisseur candidate clears the fuzzy threshold.

### Supplier matching

The OCR worker accepts a typed list of supplier candidates scoped to the current PDV:

```python
from models import SupplierCandidate

candidates = [
    SupplierCandidate(id_f=17, name="Boulangerie Durand"),
    SupplierCandidate(id_f=23, name="Grossiste Martin"),
]
```

The matched `id_f` corresponds directly to `fournisseurs.id_f` in Milady, not a list-position hack. The legacy `list[str]` form is still accepted for backward compatibility (id is derived from the 1-based list index — only safe in test fixtures or single-supplier setups).

## Integration with Milady

```php
// Milady calls this every 30s when user is on fact-form.php or cmd-form.php
$jobs = file_get_contents('https://vps/api/jobs/pending?id_pdv=5');
$jobs = json_decode($jobs);
foreach ($jobs['jobs'] as $job) {
    if ($job['doc_type'] === 'commande') {
        // Pre-fill commande form from $job['commande_result']
    } else {
        // Pre-fill facture form from $job['ocr_result']
    }
}
```

## Tests

```bash
PYTHONPATH=src python3 -m pytest tests/
```

Tests do **not** call OpenAI, do **not** require Poppler, and do **not** depend on real Mercalys PDFs. The vision call and the PDF→image step are monkeypatched.

## Calibration limitation (COM-606)

This checkout intentionally ships **without** anonymized Mercalys order samples. The prompt was authored from the field spec in the COM-606 ticket and post-meeting notes. Real prompt calibration — adjusting the system prompt, confidence thresholds, and per-field warning heuristics against 20–50 anonymized Mercalys PDFs — must happen in a subsequent pass, once Julien has assembled and anonymized the sample set. The unit tests cover parsing/persistence/matching behavior, not OCR accuracy.
