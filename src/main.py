import os
import asyncio
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional, Union

from fastapi import FastAPI, File, UploadFile, HTTPException, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic_settings import BaseSettings

from models import (
    CommandeOcrResult,
    DocumentType,
    JobDetailResponse,
    JobStatus,
    JobsPendingResponse,
    OcrJob,
    OcrResult,
    SupplierCandidate,
    SuppliersSyncRequest,
    SuppliersSyncResponse,
    UploadResponse,
)
from db import Db
from ocr import OcrWorker


class Settings(BaseSettings):
    api_key: str = "dev-key"
    openai_api_key: str = ""
    db_path: str = "/data/ocr.db"
    upload_dir: str = "/data/uploads"
    max_file_size_mb: int = 10
    ocr_model: str = "gpt-4o-mini"
    ocr_confidence_threshold: float = 0.85
    milady_webhook_url: str = ""
    milady_webhook_key: str = ""
    email_webhook_secret: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
db = Db(settings.db_path)
ocr_worker = OcrWorker(api_key=settings.openai_api_key, model=settings.ocr_model)

ALLOWED_TYPES = {"application/pdf", "image/png", "image/jpeg", "image/jpg"}


def verify_key(x_api_key: str = Header(...)):
    if x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return True


@asynccontextmanager
async def lifespan(app: FastAPI):
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="Milady OCR", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/upload", response_model=UploadResponse)
async def upload(
    file: UploadFile = File(...),
    id_pdv: int = Query(..., description="Milady PDV ID"),
    doc_type: DocumentType = Query(
        DocumentType.FACTURE,
        description="Document type: 'facture' (default, invoice) or 'commande' (Mercalys order)",
    ),
    _=Header(..., alias="x-api-key"),
):
    verify_key(_)

    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid file type: {file.content_type}")

    contents = await file.read()
    max_bytes = settings.max_file_size_mb * 1024 * 1024
    if len(contents) > max_bytes:
        raise HTTPException(status_code=413, detail=f"File too large (max {settings.max_file_size_mb}MB)")

    ext = Path(file.filename).suffix or ".bin"
    job = db.create_job(
        id_pdv=id_pdv,
        filename=file.filename,
        mime_type=file.content_type,
        file_path="",
        doc_type=doc_type,
    )

    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / f"{job.id}{ext}"
    with open(file_path, "wb") as f:
        f.write(contents)

    db.update_file_path(job.id, str(file_path))

    # Queue for background OCR
    asyncio.create_task(run_ocr(job.id, str(file_path), id_pdv, doc_type))

    return UploadResponse(job_id=job.id, status=JobStatus.PENDING, doc_type=doc_type)


# IMPORTANT: declare the static /jobs/pending route BEFORE the parameterized
# /jobs/{job_id} route. FastAPI/Starlette resolve routes in declaration order
# and "pending" would otherwise be captured as a job_id, yielding a 404.
@app.get("/jobs/pending", response_model=JobsPendingResponse)
def pending_jobs(id_pdv: int = Query(...), limit: int = Query(20, le=100), x_api_key: str = Header(...)):
    verify_key(x_api_key)
    jobs = db.list_pending_by_pdv(id_pdv, limit)
    # Mark as fetched so they don't show up again
    for job in jobs:
        db.mark_fetched(job.id)
    return JobsPendingResponse(jobs=jobs)


@app.get("/jobs/{job_id}", response_model=JobDetailResponse)
def get_job(job_id: str, x_api_key: str = Header(...)):
    verify_key(x_api_key)
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobDetailResponse(job=job)


@app.post("/suppliers/sync", response_model=SuppliersSyncResponse)
def sync_suppliers(
    payload: SuppliersSyncRequest,
    id_pdv: int = Query(..., description="Milady PDV ID"),
    x_api_key: str = Header(...),
):
    """Replace the supplier candidates cache for a single PDV.

    The Milady app pushes its `fournisseurs` rows for the user's pdv here so
    that subsequent OCR jobs for that pdv can fuzzy-match the OCR-extracted
    supplier_name against real id_f values. Full replacement (not merge) keeps
    the cache simple and avoids stale entries when suppliers are deleted in
    Milady.
    """
    verify_key(x_api_key)
    count = db.replace_supplier_candidates(id_pdv, payload.candidates)
    return SuppliersSyncResponse(id_pdv=id_pdv, count=count)


@app.post("/webhook/email")
async def email_webhook(request: Request, x_webhook_secret: str = Header(default="")):
    if x_webhook_secret != settings.email_webhook_secret:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    # Parse multipart email (SendGrid-style) or JSON
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type:
        form = await request.form()
        # TODO: extract PDF attachments from forwarded email
        return {"status": "ignored", "reason": "email parsing not yet implemented"}
    else:
        payload = await request.json()
        return {"status": "ignored", "reason": "email parsing not yet implemented"}


async def run_ocr(
    job_id: str,
    file_path: str,
    id_pdv: Optional[int] = None,
    doc_type: DocumentType = DocumentType.FACTURE,
):
    db.mark_processing(job_id)
    try:
        supplier_candidates: list[SupplierCandidate] = (
            db.list_supplier_candidates(id_pdv) if id_pdv is not None else []
        )
        result = ocr_worker.process_file(file_path, supplier_candidates, doc_type=doc_type)

        # When the cache is empty for this pdv we cannot attempt a match;
        # surface that explicitly so downstream UIs can prompt the operator
        # to sync suppliers rather than silently dropping the supplier_name.
        if not supplier_candidates and getattr(result, "supplier_name", ""):
            result.warnings.append(
                f"No supplier candidates synced for id_pdv={id_pdv}; "
                f"supplier matching skipped for '{result.supplier_name}'. "
                "Call POST /suppliers/sync to seed candidates."
            )

        db.mark_done(job_id, result)

        # Optional: auto-webhook to Milady if confidence is high
        if result.confidence >= settings.ocr_confidence_threshold and settings.milady_webhook_url:
            await notify_milady(job_id, result, doc_type)
    except Exception as e:
        db.mark_error(job_id, str(e))


async def notify_milady(
    job_id: str,
    result: Union[OcrResult, CommandeOcrResult],
    doc_type: DocumentType = DocumentType.FACTURE,
):
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                settings.milady_webhook_url,
                json={
                    "job_id": job_id,
                    "doc_type": doc_type.value,
                    "ocr_result": result.model_dump(),
                },
                headers={"x-webhook-key": settings.milady_webhook_key},
            )
    except Exception:
        pass  # Non-critical; Milady will poll anyway


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
