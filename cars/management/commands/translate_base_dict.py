"""Rewrite the `TRANSLATIONS` dict inside `templates/base.html` from the flat
`ar → en` form to a nested `ar → {en, es, ru, …}` form, translating the English
value into each target language via the Google Cloud Translation v2 REST API.

This powers the runtime fallback translation in `applyLang()` for navbar /
footer / modal text that wasn't wrapped with `class="bilingual"`.

Usage:
    GOOGLE_TRANSLATE_API_KEY=... python manage.py translate_base_dict
    python manage.py translate_base_dict --target es,ru --dry-run

Idempotent. Uses the shared `.translations_cache.json` under the `_en_<target>`
namespace.
"""

from __future__ import annotations

import html
import json
import os
import re
from pathlib import Path

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


BASE_HTML = Path(settings.BASE_DIR) / "templates" / "base.html"
CACHE_FILE = Path(settings.BASE_DIR) / ".translations_cache.json"
GT_URL = "https://translation.googleapis.com/language/translate/v2"
BATCH_SIZE = 100

# Matches the whole `var TRANSLATIONS = { ... };` block.
BLOCK_RE = re.compile(
    r"(var\s+TRANSLATIONS\s*=\s*\{)(.*?)(\};)",
    re.DOTALL,
)

# Matches a single `'ar': 'en',` entry, allowing either ' or " and an optional
# trailing comma / trailing line comment.
ENTRY_RE = re.compile(
    r"""(?P<indent>[ \t]*)
        (?P<qa>['"])(?P<ar>(?:\\.|(?!(?P=qa)).)+)(?P=qa)
        \s*:\s*
        (?P<qb>['"])(?P<en>(?:\\.|(?!(?P=qb)).)+)(?P=qb)
        \s*,?
        (?P<trail>[^\n]*)
        \n""",
    re.VERBOSE,
)


class Command(BaseCommand):
    help = "Rewrite base.html TRANSLATIONS dict to nested {en, es, ru, ...} tuples."

    def add_arguments(self, parser):
        parser.add_argument("--target", default="es,ru")
        parser.add_argument("--api-key", default=None)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        targets = [t.strip() for t in opts["target"].split(",") if t.strip()]
        api_key = opts["api_key"] or os.environ.get("GOOGLE_TRANSLATE_API_KEY")
        if not api_key:
            raise CommandError("Provide --api-key or set GOOGLE_TRANSLATE_API_KEY.")

        src = BASE_HTML.read_text(encoding="utf-8")
        block_match = BLOCK_RE.search(src)
        if not block_match:
            raise CommandError("Could not find `var TRANSLATIONS = { ... };` in base.html")

        header, body, footer = block_match.group(1), block_match.group(2), block_match.group(3)

        entries: list[tuple[str, str, str, str]] = []  # (indent, ar, en, trailing_comment)
        for m in ENTRY_RE.finditer(body):
            entries.append((
                m.group("indent"),
                _unescape_js(m.group("ar")),
                _unescape_js(m.group("en")),
                m.group("trail").strip(),
            ))

        # Skip already-nested entries (value starts with `{`): if BODY already has
        # nested form `'ar': { en: '...' }` our entry regex won't match those; that's
        # fine — we can re-run later after manual edits.
        if not entries:
            raise CommandError(
                "Parsed zero entries — the dict may already be nested. "
                "If so, this command is a no-op; hand-edit the dict if needed."
            )

        self.stdout.write(f"Parsed {len(entries)} ar→en entries.")

        cache = self._load_cache()
        # Translate each English value into every target language.
        en_values = sorted({en for _, _, en, _ in entries})
        for tgt in targets:
            bucket = cache.setdefault(f"_en_{tgt}", {})
            missing = [v for v in en_values if v not in bucket]
            if missing:
                self.stdout.write(f"Translating {len(missing)} → {tgt}")
                self._translate_batched(missing, tgt, api_key, bucket)
                self._save_cache(cache)
            else:
                self.stdout.write(f"Cache already complete for {tgt}")

        # Rebuild the dict body with nested entries.
        lines_out: list[str] = []
        # Preserve any top-level comment lines that ENTRY_RE didn't match by splicing
        # them back in. Simpler: walk the body line-by-line and rewrite lines that
        # look like key:value pairs, keep the rest unchanged.
        new_body = _rewrite_body(body, entries, targets, cache)

        new_src = src[: block_match.start()] + header + new_body + footer + src[block_match.end():]

        if opts["dry_run"]:
            preview = new_body[:400].replace("\n", "\n    ")
            self.stdout.write(f"[dry-run] new dict preview:\n    {preview}\n…")
        else:
            BASE_HTML.write_text(new_src, encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"rewrote {BASE_HTML.relative_to(settings.BASE_DIR)}"))

    # ─────── helpers ───────

    def _translate_batched(self, strings, target, api_key, bucket):
        for i in range(0, len(strings), BATCH_SIZE):
            chunk = strings[i : i + BATCH_SIZE]
            resp = requests.post(
                GT_URL,
                params={"key": api_key},
                data={"q": chunk, "source": "en", "target": target, "format": "text"},
                timeout=30,
            )
            if resp.status_code != 200:
                raise CommandError(f"Google Translate API error {resp.status_code}: {resp.text[:500]}")
            translations = resp.json()["data"]["translations"]
            for src, entry in zip(chunk, translations):
                bucket[src] = html.unescape(entry["translatedText"])

    def _load_cache(self) -> dict:
        if not CACHE_FILE.exists():
            return {}
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _save_cache(self, cache: dict) -> None:
        CACHE_FILE.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )


def _unescape_js(s: str) -> str:
    # Handle the handful of escape sequences that actually appear in this file.
    # Avoids `unicode_escape`, which mangles multi-byte Arabic UTF-8.
    if "\\" not in s:
        return s
    return (s
            .replace("\\\\", "\x00")
            .replace("\\'", "'")
            .replace('\\"', '"')
            .replace("\\n", "\n")
            .replace("\\t", "\t")
            .replace("\x00", "\\"))


def _js_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("'", "\\'")


def _rewrite_body(body: str, entries, targets, cache) -> str:
    """Replace each matched entry with the nested form, preserving indentation and trailing comments."""
    # Walk the original body line-by-line so non-entry lines (comments, blanks)
    # pass through untouched.
    entry_by_ar = {ar: (indent, en, trail) for indent, ar, en, trail in entries}
    out_lines: list[str] = []
    for raw_line in body.splitlines(keepends=True):
        m = ENTRY_RE.match(raw_line)
        if not m:
            out_lines.append(raw_line)
            continue
        ar = _unescape_js(m.group("ar"))
        en = _unescape_js(m.group("en"))
        indent = m.group("indent")
        trail = m.group("trail").strip()
        pieces = [f"en: '{_js_escape(en)}'"]
        for tgt in targets:
            translated = cache.get(f"_en_{tgt}", {}).get(en, en)
            pieces.append(f"{tgt}: '{_js_escape(translated)}'")
        joined = ", ".join(pieces)
        trail_suffix = f" {trail}" if trail else ""
        out_lines.append(f"{indent}'{_js_escape(ar)}': {{ {joined} }},{trail_suffix}\n")
    return "".join(out_lines)
