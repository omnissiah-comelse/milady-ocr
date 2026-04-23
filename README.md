# Milady OCR

Invoice OCR sidecar for Milady. Runs on a small VPS.

## What It Does

1. Receives invoice PDFs/images via upload or email forwarding
2. Runs OCR (GPT-4o-mini Vision) to extract structured data
3. Fuzzy-matches supplier against Milady's fournisseurs table
4. Queues results for review or auto-insertion
5. Milady long-polls `/jobs/pending?pdv_id=X` to fetch completed OCR jobs

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
| POST | /upload | Upload PDF/image, returns job_id |
| GET | /jobs/{job_id} | Check OCR status + result |
| GET | /jobs/pending | Long-poll for pending jobs by PDV |
| POST | /webhook/email | Receive forwarded invoice emails |
| GET | /health | Health check |

## Integration with Milady

```php
// Milady calls this every 30s when user is on fact-form.php
$jobs = file_get_contents('https://vps/api/jobs/pending?pdv_id=5&api_key=xxx');
$jobs = json_decode($jobs);
foreach($jobs as $job) {
    // Pre-fill invoice form with OCR data
}
```
