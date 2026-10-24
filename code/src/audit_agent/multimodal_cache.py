"""Lazy on-demand multimodal evidence cache.

Extracts PDFs and image console screenshots only when queried, caching to disk
to ensure O(1) lookup times and zero repeated token expenditure.
"""

import json
from pathlib import Path
from typing import Any, Optional
import pypdf
import pandas as pd


class LazyMultimodalCache:
    """Read-Through cache for PDF documents and image console screenshots."""

    def __init__(
        self,
        manifest_path: str | Path = "dataset/evidence_files.csv",
        cache_path: str | Path = "cache/multimodal_cache.json",
    ) -> None:
        self.manifest_path = Path(manifest_path)
        self.cache_path = Path(cache_path)
        self._cache: dict[str, dict[str, Any]] = {}
        self._manifest_df: Optional[pd.DataFrame] = None
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

    def get_evidence(self, file_id: str) -> Optional[dict[str, Any]]:
        """Retrieve evidence extraction lazily.
        
        If already cached -> returns immediately.
        If not cached -> extracts this single file on-demand, writes to cache, and returns.
        """
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

        # 3. Extract based on file type
        suffix = full_path.suffix.lower()
        extracted_text = ""
        extracted_entities: dict[str, list[str]] = {
            "user_ids": [],
            "emails": [],
            "phones": [],
            "resource_ids": [],
        }

        if suffix == ".pdf":
            # Extract digital vector text streams via pypdf (0 tokens, instantaneous)
            try:
                reader = pypdf.PdfReader(str(full_path))
                text_pages = [page.extract_text() or "" for page in reader.pages]
                extracted_text = "\n".join(text_pages)
            except Exception as e:
                extracted_text = f"[PDF Extraction Error: {e}]"
        elif suffix == ".png":
            # For console UI screenshots, store metadata and origin description
            extracted_text = f"[Console Screenshot: {origin} captured at {captured_at}]"

        cache_entry: dict[str, Any] = {
            "file_id": file_id,
            "file_path": str(full_path),
            "captured_at": captured_at,
            "origin": origin,
            "raw_text": extracted_text,
            "extracted_entities": extracted_entities,
        }

        # 4. Write through to cache
        self._cache[file_id] = cache_entry
        self._save_cache()
        return cache_entry
