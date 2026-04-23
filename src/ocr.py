import base64
import io
import os
from pathlib import Path
from typing import Optional

from openai import OpenAI
from pdf2image import convert_from_path
from PIL import Image
from thefuzz import fuzz, process

from models import OcrResult, OcrLineItem

MAX_IMAGE_SIZE = (2048, 2048)

SYSTEM_PROMPT = """You are an invoice OCR engine. Extract the following from the invoice image and return ONLY valid JSON.

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
- warnings: array of strings (any uncertainties)

If something is missing or unreadable, use null. Be precise with numbers."""


class OcrWorker:
    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def process_file(self, file_path: str, supplier_names: list[str]) -> OcrResult:
        ext = Path(file_path).suffix.lower()
        if ext == ".pdf":
            images = convert_from_path(file_path, dpi=200, first_page=1, last_page=1)
            if not images:
                raise ValueError("Could not convert PDF to image")
            img = images[0]
        else:
            img = Image.open(file_path)

        # Resize if too large
        if img.size[0] > MAX_IMAGE_SIZE[0] or img.size[1] > MAX_IMAGE_SIZE[1]:
            img.thumbnail(MAX_IMAGE_SIZE)

        # Convert to base64 JPEG
        buffer = io.BytesIO()
        img.convert("RGB").save(buffer, format="JPEG", quality=85)
        b64 = base64.b64encode(buffer.getvalue()).decode()

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Extract invoice data from this image. Return JSON only."},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    ],
                },
            ],
            max_tokens=2048,
            response_format={"type": "json_object"},
        )

        import json
        raw = response.choices[0].message.content
        data = json.loads(raw)

        # Build OcrResult
        line_items = [
            OcrLineItem(
                description=li.get("description", ""),
                qty=li.get("qty"),
                unit_price=li.get("unit_price"),
                total_ht=li.get("total_ht"),
            )
            for li in data.get("line_items", [])
        ]

        result = OcrResult(
            supplier_name=data.get("supplier_name", ""),
            num_fact=str(data.get("num_fact", "")),
            date_fact=data.get("date_fact"),
            total_ht=data.get("total_ht"),
            total_ttc=data.get("total_ttc"),
            tva_rate=data.get("tva_rate"),
            line_items=line_items,
            raw_text=data.get("raw_text", ""),
            confidence=float(data.get("confidence", 0.0)),
            warnings=data.get("warnings", []),
        )

        # Fuzzy match supplier
        if result.supplier_name and supplier_names:
            match, score = process.extractOne(result.supplier_name, supplier_names, scorer=fuzz.token_sort_ratio)
            if match and score >= 60:
                result.supplier_matched_id = supplier_names.index(match) + 1  # simplistic ID mapping
                result.supplier_match_score = score / 100.0
            else:
                result.warnings.append(f"Low supplier match confidence ({score}) for '{result.supplier_name}'")

        return result
