import sqlite3
import uuid
import json
from datetime import datetime
from pathlib import Path
from contextlib import contextmanager
from typing import Optional, Union

from models import (
    CommandeOcrResult,
    DocumentType,
    JobStatus,
    OcrJob,
    OcrResult,
    SupplierCandidate,
)

INIT_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    id_pdv INTEGER,
    doc_type TEXT NOT NULL DEFAULT 'facture',
    status TEXT NOT NULL DEFAULT 'pending',
    filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    file_path TEXT NOT NULL,
    ocr_result_json TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    fetched_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_pdv_status ON jobs(id_pdv, status);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

CREATE TABLE IF NOT EXISTS supplier_candidates (
    id_pdv INTEGER NOT NULL,
    id_f INTEGER NOT NULL,
    name TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (id_pdv, id_f)
);

CREATE INDEX IF NOT EXISTS idx_supplier_candidates_pdv ON supplier_candidates(id_pdv);
"""


class Db:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript(INIT_SQL)
            # Best-effort additive migration for pre-COM-606 databases that
            # were created without a doc_type column. ALTER TABLE ADD COLUMN
            # is idempotent enough when guarded by a PRAGMA check.
            cols = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
            if "doc_type" not in cols:
                conn.execute(
                    "ALTER TABLE jobs ADD COLUMN doc_type TEXT NOT NULL DEFAULT 'facture'"
                )
            conn.commit()

    def create_job(
        self,
        id_pdv: Optional[int],
        filename: str,
        mime_type: str,
        file_path: str,
        doc_type: DocumentType = DocumentType.FACTURE,
    ) -> OcrJob:
        job_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO jobs (id, id_pdv, doc_type, status, filename, mime_type, file_path, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job_id,
                    id_pdv,
                    doc_type.value,
                    JobStatus.PENDING.value,
                    filename,
                    mime_type,
                    file_path,
                    now,
                    now,
                ),
            )
            conn.commit()
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> Optional[OcrJob]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return None
        return self._row_to_job(row)

    def list_pending_by_pdv(self, id_pdv: int, limit: int = 20) -> list[OcrJob]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE id_pdv = ? AND status = 'done' AND (fetched_at IS NULL OR fetched_at < updated_at) ORDER BY created_at DESC LIMIT ?",
                (id_pdv, limit)
            ).fetchall()
        return [self._row_to_job(r) for r in rows]

    def mark_processing(self, job_id: str):
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute("UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?", (JobStatus.PROCESSING.value, now, job_id))
            conn.commit()

    def mark_done(self, job_id: str, result: Union[OcrResult, CommandeOcrResult]):
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status = ?, ocr_result_json = ?, updated_at = ? WHERE id = ?",
                (JobStatus.DONE.value, result.model_dump_json(), now, job_id)
            )
            conn.commit()

    def mark_error(self, job_id: str, error: str):
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status = ?, error_message = ?, updated_at = ? WHERE id = ?",
                (JobStatus.ERROR.value, error, now, job_id)
            )
            conn.commit()

    def update_file_path(self, job_id: str, file_path: str):
        with self._connect() as conn:
            conn.execute("UPDATE jobs SET file_path = ? WHERE id = ?", (file_path, job_id))
            conn.commit()

    def mark_fetched(self, job_id: str):
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute("UPDATE jobs SET fetched_at = ? WHERE id = ?", (now, job_id))
            conn.commit()

    # ------------------------------------------------------------------
    # Supplier candidate cache (one row per fournisseur, scoped by id_pdv)
    # ------------------------------------------------------------------

    def replace_supplier_candidates(
        self, id_pdv: int, candidates: list[SupplierCandidate]
    ) -> int:
        """Atomically swap the cached candidates for this pdv.

        Full replacement (not upsert) means rows deleted in Milady disappear
        from the cache on the next sync — matching can never pick a stale id_f.
        """
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute("DELETE FROM supplier_candidates WHERE id_pdv = ?", (id_pdv,))
            conn.executemany(
                "INSERT INTO supplier_candidates (id_pdv, id_f, name, updated_at) VALUES (?, ?, ?, ?)",
                [(id_pdv, c.id_f, c.name, now) for c in candidates],
            )
            conn.commit()
        return len(candidates)

    def list_supplier_candidates(self, id_pdv: int) -> list[SupplierCandidate]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id_f, name FROM supplier_candidates WHERE id_pdv = ? ORDER BY id_f",
                (id_pdv,),
            ).fetchall()
        return [SupplierCandidate(id_f=r["id_f"], name=r["name"]) for r in rows]

    def _row_to_job(self, row: sqlite3.Row) -> OcrJob:
        # Resolve doc_type defensively — legacy rows may have NULL.
        try:
            doc_type_raw = row["doc_type"] if "doc_type" in row.keys() else None
        except IndexError:
            doc_type_raw = None
        doc_type = DocumentType(doc_type_raw) if doc_type_raw else DocumentType.FACTURE

        ocr_result: Optional[OcrResult] = None
        commande_result: Optional[CommandeOcrResult] = None
        if row["ocr_result_json"]:
            try:
                data = json.loads(row["ocr_result_json"])
                if doc_type == DocumentType.COMMANDE:
                    commande_result = CommandeOcrResult(**data)
                else:
                    ocr_result = OcrResult(**data)
            except Exception:
                pass
        return OcrJob(
            id=row["id"],
            id_pdv=row["id_pdv"],
            doc_type=doc_type,
            status=JobStatus(row["status"]),
            filename=row["filename"],
            mime_type=row["mime_type"],
            ocr_result=ocr_result,
            commande_result=commande_result,
            error_message=row["error_message"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
