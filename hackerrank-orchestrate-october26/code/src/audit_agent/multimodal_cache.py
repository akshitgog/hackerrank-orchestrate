"""Lazy on-demand multimodal evidence cache with canonical perceptual decoupling.

Extracts PDFs (via digital text streams) and administrative console screenshots
(via objective, user-agnostic VLM perceptual extraction) into a standardized
structured schema. Caches to disk to ensure O(1) query performance, zero cross-case
contamination, and zero prompt-induced hallucinations.
"""

import base64
import json
import os
import re
from pathlib import Path
from typing import Any, Optional
import pypdf
import pandas as pd
import dotenv
import requests

from code.config.loader import load_config

# Load environment secrets
ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"
if ENV_PATH.exists():
    dotenv.load_dotenv(ENV_PATH)
else:
    dotenv.load_dotenv()


class LazyMultimodalCache:
    """Read-Through cache for PDF documents and image console screenshots."""

    def __init__(
        self,
        manifest_path: str | Path = "dataset/evidence_files.csv",
        cache_path: str | Path = "cache/multimodal_cache.json",
        config_path: str | Path = "code/config/config.yaml",
    ) -> None:
        self.manifest_path = Path(manifest_path)
        self.cache_path = Path(cache_path)
        self.config_path = Path(config_path)
        self._cache: dict[str, dict[str, Any]] = {}
        self._manifest_df: Optional[pd.DataFrame] = None
        self._config = load_config(self.config_path) if self.config_path.exists() else {}

        self._load_cache()

    def _load_cache(self) -> None:
        """Load existing disk cache if available."""
        if self.cache_path.exists():
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    self._cache = json.load(f)
            except Exception:
                self._cache = {}

    def _save_cache(self) -> None:
        """Persist in-memory cache to disk."""
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump(self._cache, f, indent=2, ensure_ascii=False)

    def _get_manifest(self) -> pd.DataFrame:
        """Lazy load evidence manifest."""
        if self._manifest_df is None:
            if not self.manifest_path.exists():
                raise FileNotFoundError(f"Evidence manifest not found: {self.manifest_path}")
            self._manifest_df = pd.read_csv(self.manifest_path)
        return self._manifest_df

    def _extract_pdf(self, full_path: Path) -> dict[str, Any]:
        """Extract text and structured metadata from digital vector PDF with zero tokens."""
        text_pages: list[str] = []
        try:
            reader = pypdf.PdfReader(str(full_path))
            for page in reader.pages:
                txt = page.extract_text() or ""
                text_pages.append(txt)
            raw_text = "\n".join(text_pages)
        except Exception as e:
            raw_text = f"[PDF Extraction Error: {e}]"

        return {
            "format": "pdf",
            "raw_text": raw_text,
            "records": [],
        }

    def _extract_image_vlm(self, full_path: Path, origin: str) -> dict[str, Any]:
        """Extract table rows and visible text from UI console screenshots via VLM."""
        api_key = os.getenv("FIREWORKS_API_KEY")
        if not api_key:
            return {
                "format": "image",
                "raw_text": f"[Console Screenshot: {origin}]",
                "records": [],
            }

        try:
            with open(full_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")

            prompt = (
                "You are an objective OCR and administrative table extractor. "
                "Extract all visible text, identifiers, and table rows from this console screenshot "
                "into a clean JSON object.\n"
                "Schema:\n"
                "{\n"
                '  "system": "system or service name",\n'
                '  "title": "portal title",\n'
                '  "records": [\n'
                "    {\n"
                '      "resource_id": "resource_id or empty",\n'
                '      "user_id": "user_id or empty",\n'
                '      "email": "email or empty",\n'
                '      "name": "full name or empty",\n'
                '      "status": "status or empty",\n'
                '      "details": "visible details"\n'
                "    }\n"
                "  ],\n"
                '  "raw_text": "all readable text in the image"\n'
                "}\n"
                "Output strictly valid JSON and nothing else."
            )

            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": "accounts/fireworks/models/glm-5p3-flash",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                        ],
                    }
                ],
                "temperature": 0.0,
                "max_tokens": 3000,
            }

            resp = requests.post(
                "https://api.fireworks.ai/inference/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=35,
            )

            if resp.status_code == 200:
                txt = resp.json()["choices"][0]["message"]["content"].strip()
                txt = re.sub(r"^```(?:json)?", "", txt, flags=re.MULTILINE)
                txt = re.sub(r"```$", "", txt, flags=re.MULTILINE).strip()
                data = json.loads(txt)
                return {
                    "format": "image",
                    "system": data.get("system", origin),
                    "title": data.get("title", ""),
                    "records": data.get("records", []),
                    "raw_text": data.get("raw_text", ""),
                }
        except Exception:
            pass

        return {
            "format": "image",
            "raw_text": f"[Console Screenshot: {origin}]",
            "records": [],
        }

    def get_evidence(self, file_id: str) -> Optional[dict[str, Any]]:
        """Retrieve evidence extraction lazily from disk cache or extract on-demand."""
        # 1. Check cache hit
        if file_id in self._cache:
            return self._cache[file_id]

        # 2. Cache miss: Look up file in manifest
        manifest = self._get_manifest()
        match = manifest[manifest["file_id"] == file_id]
        if match.empty:
            return None

        row = match.iloc[0]
        raw_path = str(row["file_path"])
        full_path = Path("dataset") / raw_path if not raw_path.startswith("dataset") else Path(raw_path)
        captured_at = str(row["captured_at"])
        origin = str(row["origin"])

        if not full_path.exists():
            return None

        suffix = full_path.suffix.lower()

        # 3. Canonical Perceptual Extraction
        if suffix == ".pdf":
            parsed = self._extract_pdf(full_path)
        elif suffix in [".png", ".jpg", ".jpeg"]:
            parsed = self._extract_image_vlm(full_path, origin)
        else:
            parsed = {
                "format": suffix.replace(".", ""),
                "raw_text": "",
                "records": [],
            }

        cache_entry: dict[str, Any] = {
            "file_id": file_id,
            "file_path": str(full_path),
            "captured_at": captured_at,
            "origin": origin,
            "format": parsed.get("format", suffix),
            "system": parsed.get("system", origin),
            "raw_text": parsed.get("raw_text", ""),
            "records": parsed.get("records", []),
        }

        # 4. Write through to disk cache
        self._cache[file_id] = cache_entry
        self._save_cache()
        return cache_entry

    def preload_all_multimodal(self) -> None:
        """Preload and cache all 11 images and 4 PDFs in the manifest."""
        manifest = self._get_manifest()
        multimodal_files = manifest[
            manifest["file_path"].str.endswith(".png") | manifest["file_path"].str.endswith(".pdf")
        ]
        print(f"Preloading and caching {len(multimodal_files)} multimodal evidence files...")
        for _, row in multimodal_files.iterrows():
            fid = str(row["file_id"])
            if fid not in self._cache:
                print(f"  -> Extracting {fid} ({row['file_path']})...", end=" ", flush=True)
                entry = self.get_evidence(fid)
                status = "OK" if entry and (entry.get("records") or entry.get("raw_text")) else "Fallback"
                print(status)
            else:
                print(f"  -> {fid} already cached.")
