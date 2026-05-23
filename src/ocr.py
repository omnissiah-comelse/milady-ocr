import base64
import io
import json
from pathlib import Path
from typing import Optional, Union

from openai import OpenAI
from pdf2image import convert_from_path
from PIL import Image
from thefuzz import fuzz, process

from models import (
    CommandeLineItem,
    CommandeOcrResult,
    DocumentType,
    OcrLineItem,
    OcrResult,
    SupplierCandidate,
    SupplierMatch,
)

MAX_IMAGE_SIZE = (2048, 2048)

# Tolerance applied when reconciling total_ht with the sum of line_items.
# 1 cent absolute slack to swallow rounding plus 0.5% relative slack to
# tolerate VAT rounding on multi-line orders.
AMOUNT_ABS_TOLERANCE = 0.01
AMOUNT_REL_TOLERANCE = 0.005

SUPPLIER_MATCH_MIN_SCORE = 60  # thefuzz score (0..100)


FACTURE_SYSTEM_PROMPT = """You are an invoice OCR engine. Extract the following from the invoice image and return ONLY valid JSON.

Required fields:
- supplier_name: string (company name on the invoice)
- num_fact: string (invoice number)
- date_fact: string (invoice date as YYYY-MM-DD, or null)
- total_ht: number (total before tax, or null)
- total_ttc: number (total with tax, or null)
- tva_rate: number (VAT rate percentage, e.g. 20.0, or null)
- line_items: array of objects with {description, qty, unit_price, total_ht}
- raw_text: string (all text you can read)
- confidence: number (0.0 to 1.0, your confidence in this extraction)
- field_confidence: object mapping field names to numbers in 0.0..1.0
- warnings: array of strings (any uncertainties)

If something is missing or unreadable, use null. Be precise with numbers."""


COMMANDE_SYSTEM_PROMPT = """You are an order ("bon de commande") OCR engine for Mercalys order exports. Extract the following from the order image and return ONLY valid JSON.

Required fields:
- supplier_name: string (fournisseur on the order)
- num_cmd: string (order number / numero de commande)
- num_bl: string or null (delivery note / bon de livraison number if present)
- date_cmd: string (order date as YYYY-MM-DD, or null)
- total_ht: number (total before tax, or null)
- line_items: array of objects with:
    - description: string
    - qty: number or null
    - unit_price: number or null
    - total_ht: number or null
    - cost_center_label: string or null (rayon / centre de cout label, e.g. "BOULANGERIE")
    - cost_center_code: string or null (rayon / centre de cout code if visible)
- raw_text: string (all text you can read)
- confidence: number (0.0 to 1.0, your overall confidence)
- field_confidence: object mapping field names to numbers in 0.0..1.0 (include at least num_cmd, date_cmd, total_ht, supplier_name)
- warnings: array of strings (any uncertainties)

Mercalys orders typically have a header block with supplier, an order number prefixed "CMD" or similar, and a line-item table including rayon/centre de cout. If something is missing or unreadable, use null. Be precise with numbers."""


def _amounts_reconcile(total: Optional[float], line_items_total: float) -> bool:
    if total is None:
        return True  # nothing to reconcile
    diff = abs(total - line_items_total)
    return diff <= max(AMOUNT_ABS_TOLERANCE, AMOUNT_REL_TOLERANCE * abs(total))


def _sum_line_items(items) -> float:
    return sum((it.total_ht or 0.0) for it in items)


def _coerce_str(value) -> str:
    if value is None:
        return ""
    return str(value)


def _normalize_supplier_candidates(
    supplier_candidates: Optional[Union[list[SupplierCandidate], list[str], list[dict]]]
) -> list[SupplierCandidate]:
    """Accept the legacy list[str] form or the new typed form.

    Legacy list[str] is preserved for backward compatibility — when only names
    are supplied, the candidate id_f is set to the 1-based list index. New
    callers should pass SupplierCandidate instances so the matched id is a
    real Milady fournisseurs.id_f.
    """
    if not supplier_candidates:
        return []
    out: list[SupplierCandidate] = []
    for i, c in enumerate(supplier_candidates, start=1):
        if isinstance(c, SupplierCandidate):
            out.append(c)
        elif isinstance(c, str):
            out.append(SupplierCandidate(id_f=i, name=c))
        elif isinstance(c, dict):
            out.append(SupplierCandidate(**c))
        else:
            # Best effort: skip unknown shape
            continue
    return out


def _match_supplier(
    supplier_name: str,
    candidates: list[SupplierCandidate],
) -> tuple[Optional[SupplierMatch], Optional[str]]:
    """Return (match, warning). match is None when no candidate clears the threshold."""
    if not supplier_name or not candidates:
        return None, None
    name_index = {c.name: c for c in candidates}
    names = list(name_index.keys())
    best = process.extractOne(supplier_name, names, scorer=fuzz.token_sort_ratio)
    if not best:
        return None, None
    match_name, score = best
    if score >= SUPPLIER_MATCH_MIN_SCORE:
        cand = name_index[match_name]
        return (
            SupplierMatch(id_f=cand.id_f, name=cand.name, score=score / 100.0),
            None,
        )
    return None, (
        f"No supplier match (best='{match_name}' score={score}) for '{supplier_name}'"
    )


class OcrWorker:
    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        self.client = OpenAI(api_key=api_key)
        self.model = model

    # ------------------------------------------------------------------
    # File -> image
    # ------------------------------------------------------------------

    def _load_image_b64(self, file_path: str) -> str:
        ext = Path(file_path).suffix.lower()
        if ext == ".pdf":
            images = convert_from_path(file_path, dpi=200, first_page=1, last_page=1)
            if not images:
                raise ValueError("Could not convert PDF to image")
            img = images[0]
        else:
            img = Image.open(file_path)
        if img.size[0] > MAX_IMAGE_SIZE[0] or img.size[1] > MAX_IMAGE_SIZE[1]:
            img.thumbnail(MAX_IMAGE_SIZE)
        buffer = io.BytesIO()
        img.convert("RGB").save(buffer, format="JPEG", quality=85)
        return base64.b64encode(buffer.getvalue()).decode()

    def _vision_extract(self, b64: str, system_prompt: str, user_text: str) -> dict:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    ],
                },
            ],
            max_tokens=2048,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content
        return json.loads(raw)

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def process_file(
        self,
        file_path: str,
        supplier_names: Optional[Union[list[str], list[SupplierCandidate]]] = None,
        doc_type: DocumentType = DocumentType.FACTURE,
    ) -> Union[OcrResult, CommandeOcrResult]:
        candidates = _normalize_supplier_candidates(supplier_names)
        if doc_type == DocumentType.COMMANDE:
            return self.process_commande(file_path, candidates)
        return self.process_facture(file_path, candidates)

    def process_facture(
        self, file_path: str, supplier_candidates: list[SupplierCandidate]
    ) -> OcrResult:
        b64 = self._load_image_b64(file_path)
        data = self._vision_extract(
            b64,
            FACTURE_SYSTEM_PROMPT,
            "Extract invoice data from this image. Return JSON only.",
        )
        return self.parse_facture(data, supplier_candidates)

    def process_commande(
        self, file_path: str, supplier_candidates: list[SupplierCandidate]
    ) -> CommandeOcrResult:
        b64 = self._load_image_b64(file_path)
        data = self._vision_extract(
            b64,
            COMMANDE_SYSTEM_PROMPT,
            "Extract Mercalys order data from this image. Return JSON only.",
        )
        return self.parse_commande(data, supplier_candidates)

    # ------------------------------------------------------------------
    # JSON parsers (extracted so tests can hit them without a vision call)
    # ------------------------------------------------------------------

    @staticmethod
    def parse_facture(
        data: dict, supplier_candidates: list[SupplierCandidate]
    ) -> OcrResult:
        line_items = [
            OcrLineItem(
                description=_coerce_str(li.get("description", "")),
                qty=li.get("qty"),
                unit_price=li.get("unit_price"),
                total_ht=li.get("total_ht"),
            )
            for li in (data.get("line_items") or [])
        ]
        result = OcrResult(
            supplier_name=_coerce_str(data.get("supplier_name", "")),
            num_fact=_coerce_str(data.get("num_fact", "")),
            date_fact=data.get("date_fact"),
            total_ht=data.get("total_ht"),
            total_ttc=data.get("total_ttc"),
            tva_rate=data.get("tva_rate"),
            line_items=line_items,
            raw_text=_coerce_str(data.get("raw_text", "")),
            confidence=float(data.get("confidence", 0.0) or 0.0),
            field_confidence=data.get("field_confidence") or {},
            warnings=list(data.get("warnings") or []),
        )

        # Amount reconciliation for facture (HT side).
        li_total = _sum_line_items(line_items)
        if line_items and not _amounts_reconcile(result.total_ht, li_total):
            result.warnings.append(
                f"total_ht ({result.total_ht}) does not match sum of line items ({li_total:.2f})"
            )

        match, warn = _match_supplier(result.supplier_name, supplier_candidates)
        if match is not None:
            result.supplier_matched_id = match.id_f
            result.supplier_match_score = match.score
        elif warn:
            result.warnings.append(warn)
        return result

    @staticmethod
    def parse_commande(
        data: dict, supplier_candidates: list[SupplierCandidate]
    ) -> CommandeOcrResult:
        line_items = [
            CommandeLineItem(
                description=_coerce_str(li.get("description", "")),
                qty=li.get("qty"),
                unit_price=li.get("unit_price"),
                total_ht=li.get("total_ht"),
                cost_center_label=li.get("cost_center_label"),
                cost_center_code=li.get("cost_center_code"),
            )
            for li in (data.get("line_items") or [])
        ]
        result = CommandeOcrResult(
            supplier_name=_coerce_str(data.get("supplier_name", "")),
            num_cmd=_coerce_str(data.get("num_cmd", "")),
            num_bl=data.get("num_bl"),
            date_cmd=data.get("date_cmd"),
            total_ht=data.get("total_ht"),
            line_items=line_items,
            raw_text=_coerce_str(data.get("raw_text", "")),
            confidence=float(data.get("confidence", 0.0) or 0.0),
            field_confidence=data.get("field_confidence") or {},
            warnings=list(data.get("warnings") or []),
        )

        li_total = _sum_line_items(line_items)
        if line_items and not _amounts_reconcile(result.total_ht, li_total):
            result.warnings.append(
                f"total_ht ({result.total_ht}) does not match sum of line items ({li_total:.2f})"
            )

        match, warn = _match_supplier(result.supplier_name, supplier_candidates)
        if match is not None:
            result.supplier_match = match
        elif warn:
            result.warnings.append(warn)
        return result
