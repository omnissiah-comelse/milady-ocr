import sqlite3
import uuid
import json
from datetime import datetime
from pathlib import Path
from contextlib import contextmanager
from typing import Optional

from models import OcrJob, JobStatus, OcrResult, OcrLineItem

INIT_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    id_pdv INTEGER,
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
            conn.commit()

    def create_job(self, id_pdv: Optional[int], filename: str, mime_type: str, file_path: str) -> OcrJob:
        job_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO jobs (id, id_pdv, status, filename, mime_type, file_path, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (job_id, id_pdv, JobStatus.PENDING.value, filename, mime_type, file_path, now, now)
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

    def mark_done(self, job_id: str, result: OcrResult):
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

    def _row_to_job(self, row: sqlite3.Row) -> OcrJob:
        ocr_result = None
        if row["ocr_result_json"]:
            try:
                data = json.loads(row["ocr_result_json"])
                ocr_result = OcrResult(**data)
            except Exception:
                pass
        return OcrJob(
            id=row["id"],
            id_pdv=row["id_pdv"],
            status=JobStatus(row["status"]),
            filename=row["filename"],
            mime_type=row["mime_type"],
            ocr_result=ocr_result,
            error_message=row["error_message"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
