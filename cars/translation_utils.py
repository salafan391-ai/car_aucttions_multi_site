"""Runtime Google Translate v2 helper, sharing the .translations_cache.json
file used by cars/management/commands/translate_templates.py.

Silent no-op when GOOGLE_TRANSLATE_API_KEY is unset — callers fall back to
the source string.
"""

from __future__ import annotations

import html
import json
import os
import threading
from pathlib import Path
from typing import Iterable

import requests
from django.conf import settings


CACHE_FILE = Path(settings.BASE_DIR) / ".translations_cache.json"
GT_URL = "https://translation.googleapis.com/language/translate/v2"
BATCH_SIZE = 100

_cache_lock = threading.Lock()


def _load_cache() -> dict:
    if not CACHE_FILE.exists():
        return {}
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_cache(cache: dict) -> None:
    CACHE_FILE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def translate_batch(strings: Iterable[str], targets: Iterable[str], source: str = "ar") -> dict[str, dict[str, str]]:
    """Return {source_string: {target_lang: translated_string}}.

    Hits cache first; translates misses via the Google Cloud Translation v2
    REST API, then writes the cache back. Returns the source string as the
    fallback when the key is unset or an API call fails.
    """
    unique = sorted({s for s in strings if s and s.strip()})
    targets = [t for t in targets if t and t != source]
    if not unique or not targets:
        return {s: {} for s in unique}

    api_key = os.environ.get("GOOGLE_TRANSLATE_API_KEY")

    with _cache_lock:
        cache = _load_cache()
        dirty = False

        if api_key:
            for tgt in targets:
                bucket = cache.setdefault(tgt, {})
                missing = [s for s in unique if s not in bucket]
                for i in range(0, len(missing), BATCH_SIZE):
                    chunk = missing[i:i + BATCH_SIZE]
                    try:
                        resp = requests.post(
                            GT_URL,
                            params={"key": api_key},
                            data={"q": chunk, "source": source, "target": tgt, "format": "text"},
                            timeout=30,
                        )
                        resp.raise_for_status()
                        translations = resp.json()["data"]["translations"]
                        for src, entry in zip(chunk, translations):
                            bucket[src] = html.unescape(entry["translatedText"])
                        dirty = True
                    except (requests.RequestException, KeyError, ValueError):
                        break

        if dirty:
            _save_cache(cache)

    return {
        s: {tgt: cache.get(tgt, {}).get(s, s) for tgt in targets}
        for s in unique
    }
