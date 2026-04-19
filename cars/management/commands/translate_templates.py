"""Scan HTML templates and fill `data-lang-<target>` attributes by translating
the existing `data-lang-ar` values via the Google Cloud Translation v2 REST API.

Also handles the parallel attribute families: `data-title-ar`,
`data-placeholder-ar`, `data-aria-label-ar`.

Usage:
    GOOGLE_TRANSLATE_API_KEY=... python manage.py translate_templates
    python manage.py translate_templates --target es,ru --api-key KEY --dry-run

Idempotent: re-runs skip elements that already have the target attribute, and
translations are cached to `.translations_cache.json` at the project root.

Dynamic values containing `{{ ... }}` or `{% ... %}` are skipped — at runtime
the JS fallback chain (data-lang-<target> → data-lang-en → data-lang-ar) will
keep them on the English/Arabic rendered value.
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


TEMPLATES_DIR = Path(settings.BASE_DIR) / "templates"
CACHE_FILE = Path(settings.BASE_DIR) / ".translations_cache.json"

# Attribute families — (source attribute, common prefix for target variants).
ATTR_FAMILIES: list[tuple[str, str]] = [
    ("data-lang-ar", "data-lang"),
    ("data-title-ar", "data-title"),
    ("data-placeholder-ar", "data-placeholder"),
    ("data-aria-label-ar", "data-aria-label"),
]

DJANGO_SIGILS = ("{{", "{%")

GT_URL = "https://translation.googleapis.com/language/translate/v2"
BATCH_SIZE = 100


class Command(BaseCommand):
    help = (
        "Scan HTML templates for `data-lang-ar` / `data-title-ar` / "
        "`data-placeholder-ar` / `data-aria-label-ar` and inject translated "
        "counterparts for the given target languages using the Google Cloud "
        "Translation v2 REST API."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--target",
            default="es,ru",
            help="Comma-separated ISO-639-1 target codes (default: es,ru).",
        )
        parser.add_argument(
            "--api-key",
            default=None,
            help="Google Translate API key. Falls back to GOOGLE_TRANSLATE_API_KEY env var.",
        )
        parser.add_argument(
            "--paths",
            default=str(TEMPLATES_DIR),
            help="Root directory to scan recursively. Defaults to the project templates/ dir.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would change without writing files.",
        )

    def handle(self, *args, **opts):
        targets = [t.strip() for t in opts["target"].split(",") if t.strip()]
        api_key = opts["api_key"] or os.environ.get("GOOGLE_TRANSLATE_API_KEY")
        if not api_key:
            raise CommandError(
                "Provide --api-key or set GOOGLE_TRANSLATE_API_KEY."
            )

        root = Path(opts["paths"])
        if not root.exists():
            raise CommandError(f"Path does not exist: {root}")

        dry = opts["dry_run"]
        cache = self._load_cache()

        html_files = list(root.rglob("*.html"))
        self.stdout.write(f"Scanning {len(html_files)} template(s) under {root}")

        # Phase 1 — read every file and collect unique source strings.
        file_contents: dict[Path, str] = {}
        needed: set[str] = set()
        for path in html_files:
            content = path.read_text(encoding="utf-8")
            file_contents[path] = content
            for src_attr, _prefix in ATTR_FAMILIES:
                for m in re.finditer(rf'{re.escape(src_attr)}="([^"]*)"', content):
                    val = m.group(1)
                    if not val.strip():
                        continue
                    if any(sigil in val for sigil in DJANGO_SIGILS):
                        continue
                    needed.add(val)

        if not needed:
            self.stdout.write("No static Arabic attribute values found. Nothing to translate.")
            return

        # Phase 2 — fill the cache for each target.
        for tgt in targets:
            cache.setdefault(tgt, {})
            missing = sorted(s for s in needed if s not in cache[tgt])
            if missing:
                self.stdout.write(f"Translating {len(missing)} string(s) → {tgt}")
                self._translate_batched(missing, tgt, api_key, cache[tgt])
                self._save_cache(cache)
            else:
                self.stdout.write(f"Cache already has every string for {tgt}")

        # Phase 3 — rewrite files.
        modified = 0
        for path, content in file_contents.items():
            new_content = self._inject(content, targets, cache)
            if new_content == content:
                continue
            modified += 1
            if dry:
                self.stdout.write(f"[dry-run] would update {path.relative_to(settings.BASE_DIR)}")
            else:
                path.write_text(new_content, encoding="utf-8")
                self.stdout.write(self.style.SUCCESS(f"updated {path.relative_to(settings.BASE_DIR)}"))

        verb = "would update" if dry else "updated"
        self.stdout.write(self.style.SUCCESS(f"Done. {verb} {modified} file(s)."))

    # ─────────────────────────── internals ───────────────────────────

    def _inject(self, content: str, targets: list[str], cache: dict) -> str:
        for src_attr, prefix in ATTR_FAMILIES:
            for tgt in targets:
                tgt_attr = f"{prefix}-{tgt}"
                # Match the source attribute only when the same tag does not
                # already contain the target attribute. The negative lookahead
                # `[^<>]*` limits the search to the current tag.
                pattern = re.compile(
                    rf'({re.escape(src_attr)}="([^"]*)")(?![^<>]*{re.escape(tgt_attr)}=)'
                )

                def repl(m: re.Match[str]) -> str:
                    full_match, src_val = m.group(0), m.group(2)
                    if not src_val.strip():
                        return full_match
                    if any(sigil in src_val for sigil in DJANGO_SIGILS):
                        return full_match
                    tr = cache.get(tgt, {}).get(src_val)
                    if tr is None:
                        return full_match
                    escaped = tr.replace('"', "&quot;")
                    return f'{m.group(1)} {tgt_attr}="{escaped}"'

                content = pattern.sub(repl, content)
        return content

    def _translate_batched(
        self,
        strings: list[str],
        target: str,
        api_key: str,
        cache_for_target: dict,
    ) -> None:
        for i in range(0, len(strings), BATCH_SIZE):
            chunk = strings[i : i + BATCH_SIZE]
            resp = requests.post(
                GT_URL,
                params={"key": api_key},
                data={"q": chunk, "source": "ar", "target": target, "format": "text"},
                timeout=30,
            )
            if resp.status_code != 200:
                raise CommandError(
                    f"Google Translate API error {resp.status_code}: {resp.text[:500]}"
                )
            translations = resp.json()["data"]["translations"]
            for src, entry in zip(chunk, translations):
                cache_for_target[src] = html.unescape(entry["translatedText"])

    def _load_cache(self) -> dict:
        if not CACHE_FILE.exists():
            return {}
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            self.stdout.write(self.style.WARNING(f"Cache at {CACHE_FILE} is corrupt; starting fresh."))
            return {}

    def _save_cache(self, cache: dict) -> None:
        CACHE_FILE.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
