import os
import asyncio
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, UploadFile, HTTPException, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic_settings import BaseSettings

from models import UploadResponse, JobsPendingResponse, JobDetailResponse, OcrJob, JobStatus
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
    job = db.create_job(id_pdv=id_pdv, filename=file.filename, mime_type=file.content_type, file_path="")

    file_path = Path(settings.upload_dir) / f"{job.id}{ext}"
    with open(file_path, "wb") as f:
        f.write(contents)

    db.update_file_path(job.id, str(file_path))

    # Queue for background OCR
    asyncio.create_task(run_ocr(job.id, str(file_path)))

    return UploadResponse(job_id=job.id, status=JobStatus.PENDING)


@app.get("/jobs/{job_id}", response_model=JobDetailResponse)
def get_job(job_id: str, x_api_key: str = Header(...)):
    verify_key(x_api_key)
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobDetailResponse(job=job)


@app.get("/jobs/pending", response_model=JobsPendingResponse)
def pending_jobs(id_pdv: int = Query(...), limit: int = Query(20, le=100), x_api_key: str = Header(...)):
    verify_key(x_api_key)
    jobs = db.list_pending_by_pdv(id_pdv, limit)
    # Mark as fetched so they don't show up again
    for job in jobs:
        db.mark_fetched(job.id)
    return JobsPendingResponse(jobs=jobs)


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


async def run_ocr(job_id: str, file_path: str):
    db.mark_processing(job_id)
    try:
        # TODO: fetch actual supplier names from Milady DB or cache
        supplier_names = []
        result = ocr_worker.process_file(file_path, supplier_names)
        db.mark_done(job_id, result)

        # Optional: auto-webhook to Milady if confidence is high
        if result.confidence >= settings.ocr_confidence_threshold and settings.milady_webhook_url:
            await notify_milady(job_id, result)
    except Exception as e:
        db.mark_error(job_id, str(e))


async def notify_milady(job_id: str, result):
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                settings.milady_webhook_url,
                json={"job_id": job_id, "ocr_result": result.model_dump()},
                headers={"x-webhook-key": settings.milady_webhook_key},
            )
    except Exception:
        pass  # Non-critical; Milady will poll anyway


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
