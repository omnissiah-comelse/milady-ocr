from datetime import datetime
from enum import Enum
from typing import Optional, Union
from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    ERROR = "error"


class DocumentType(str, Enum):
    FACTURE = "facture"
    COMMANDE = "commande"


class SupplierCandidate(BaseModel):
    """Typed supplier candidate scoped to a single PDV.

    Replaces the previous list[str] supplier API so that the matched id
    corresponds to the real Milady fournisseurs.id_f rather than a list
    position.
    """
    id_f: int
    name: str


class SupplierMatch(BaseModel):
    id_f: Optional[int] = None
    name: Optional[str] = None
    score: Optional[float] = None  # 0.0..1.0


# ---------- Facture (invoice) ----------

class OcrLineItem(BaseModel):
    description: str = ""
    qty: Optional[float] = None
    unit_price: Optional[float] = None
    total_ht: Optional[float] = None


class OcrResult(BaseModel):
    """Facture / invoice OCR result. Kept name & shape for backward compat."""
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
    field_confidence: dict[str, float] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


# ---------- Commande (Mercalys order) ----------

class CommandeLineItem(BaseModel):
    description: str = ""
    qty: Optional[float] = None
    unit_price: Optional[float] = None
    total_ht: Optional[float] = None
    # Cost center hint extracted from the order line. Mercalys orders often
    # carry a "centre de coût / rayon" column that maps to Milady cdc.
    cost_center_label: Optional[str] = None
    cost_center_code: Optional[str] = None


class CommandeOcrResult(BaseModel):
    supplier_name: str = ""
    supplier_match: SupplierMatch = Field(default_factory=SupplierMatch)
    num_cmd: str = ""
    num_bl: Optional[str] = None
    date_cmd: Optional[str] = None  # ISO YYYY-MM-DD
    total_ht: Optional[float] = None
    line_items: list[CommandeLineItem] = Field(default_factory=list)
    raw_text: str = ""
    confidence: float = 0.0
    field_confidence: dict[str, float] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


# ---------- Job envelope ----------

class OcrJob(BaseModel):
    id: str
    id_pdv: Optional[int] = None
    doc_type: DocumentType = DocumentType.FACTURE
    status: JobStatus
    filename: str
    mime_type: str
    ocr_result: Optional[OcrResult] = None
    commande_result: Optional[CommandeOcrResult] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class UploadResponse(BaseModel):
    job_id: str
    status: JobStatus
    doc_type: DocumentType = DocumentType.FACTURE
    message: str = "Upload received, OCR queued"


class JobsPendingResponse(BaseModel):
    jobs: list[OcrJob]


class JobDetailResponse(BaseModel):
    job: OcrJob


# ---------- Supplier candidate sync (Milady -> sidecar) ----------

class SuppliersSyncRequest(BaseModel):
    """Body for POST /suppliers/sync.

    Milady pushes its `fournisseurs` rows for one pdv. The sidecar replaces
    (not merges) the local cache so that deletions/renames in Milady are
    reflected. The list can be empty to clear the cache for that pdv.
    """
    candidates: list[SupplierCandidate] = Field(default_factory=list)


class SuppliersSyncResponse(BaseModel):
    id_pdv: int
    count: int
