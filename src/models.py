from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    ERROR = "error"


class OcrLineItem(BaseModel):
    description: str = ""
    qty: Optional[float] = None
    unit_price: Optional[float] = None
    total_ht: Optional[float] = None


class OcrResult(BaseModel):
    supplier_name: str = ""
    supplier_matched_id: Optional[int] = None
    supplier_match_score: Optional[float] = None
    num_fact: str = ""
    date_fact: Optional[str] = None  # ISO YYYY-MM-DD
    total_ht: Optional[float] = None
    total_ttc: Optional[float] = None
    tva_rate: Optional[float] = None
    line_items: list[OcrLineItem] = Field(default_factory=list)
    raw_text: str = ""
    confidence: float = 0.0
    warnings: list[str] = Field(default_factory=list)


class OcrJob(BaseModel):
    id: str
    id_pdv: Optional[int] = None
    status: JobStatus
    filename: str
    mime_type: str
    ocr_result: Optional[OcrResult] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class UploadResponse(BaseModel):
    job_id: str
    status: JobStatus
    message: str = "Upload received, OCR queued"


class JobsPendingResponse(BaseModel):
    jobs: list[OcrJob]


class JobDetailResponse(BaseModel):
    job: OcrJob
