import json
import hashlib
import tempfile
import os
from pathlib import Path

class ResponseCache:
    def __init__(self, cache_dir: str):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def cache_key(self, model: str, prompt_hash: str, media_hash: str = "") -> str:
        data = f"{model}:{prompt_hash}:{media_hash}".encode("utf-8")
        return hashlib.sha256(data).hexdigest()

    def get(self, key: str) -> dict | None:
        cache_file = self.cache_dir / f"{key}.json"
        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                return None
        return None

    def put(self, key: str, response: dict) -> None:
        cache_file = self.cache_dir / f"{key}.json"
        temp_file = self.cache_dir / f"{key}.tmp"
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(response, f)
            os.replace(temp_file, cache_file)
        except OSError:
            if temp_file.exists():
                try:
                    os.remove(temp_file)
                except OSError:
                    pass
