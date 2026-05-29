"""Translate Encar ``optionsChoice`` option names + descriptions and emit
``cars/options_choice_i18n.json`` (English-pivoted, like ``translate_enums``).

The detail page renders ``extra_features.optionsChoice`` — a list of factory
option dicts whose ``optionName`` / ``description`` are Korean. This command:

  Stage 1  collect every unique Korean ``optionName`` / ``description`` across
           all ApiCar rows and translate Korean -> English.
  Stage 2  collect the unique English strings and translate English -> ar/ru/es.

The JSON it writes is consumed at runtime by ``cars/options_choice_i18n.py`` and
the ``oc`` template filter. No DB writes — the cars keep their Korean data.

Usage (reads the cars from whatever DB ``DATABASE_URL`` points at; translation
needs a Google Translate v2 key)::

    DATABASE_URL=<public-url> GOOGLE_TRANSLATE_API_KEY=... \
        python manage.py translate_options_choice
    python manage.py translate_options_choice --target ar,es,ru --limit 2000 --dry-run

Idempotent: translations are cached in the same ``.translations_cache.json`` used
by ``translate_templates`` / ``translate_enums``, under sections ``_ko_en`` and
``_en_<target>``. Re-running only translates strings not already cached.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from cars.models import ApiCar

CACHE_FILE = Path(settings.BASE_DIR) / ".translations_cache.json"
OUTPUT_FILE = Path(settings.BASE_DIR) / "cars" / "options_choice_i18n.json"
GT_URL = "https://translation.googleapis.com/language/translate/v2"
BATCH_SIZE = 100


class Command(BaseCommand):
    help = "Translate Encar optionsChoice strings and emit cars/options_choice_i18n.json."

    def add_arguments(self, parser):
        parser.add_argument("--target", default="ar,es,ru",
                            help="Comma-separated languages to translate English into.")
        parser.add_argument("--api-key", default=None)
        parser.add_argument("--limit", type=int, default=None,
                            help="Only scan the first N cars (for testing).")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        import os

        targets = [t.strip() for t in opts["target"].split(",") if t.strip()]
        api_key = opts["api_key"] or os.environ.get("GOOGLE_TRANSLATE_API_KEY")
        if not api_key:
            raise CommandError("Provide --api-key or set GOOGLE_TRANSLATE_API_KEY.")

        # ── collect unique Korean strings ──
        names: set[str] = set()
        descs: set[str] = set()
        qs = (ApiCar.objects
              .filter(extra_features__has_key="optionsChoice")
              .only("extra_features"))
        if opts["limit"]:
            qs = qs[: opts["limit"]]

        scanned = 0
        for car in qs.iterator(chunk_size=2000):
            choice = (car.extra_features or {}).get("optionsChoice") or []
            if not isinstance(choice, list):
                continue
            scanned += 1
            for o in choice:
                if not isinstance(o, dict):
                    continue
                n = (o.get("optionName") or "").strip()
                d = (o.get("description") or "").strip()
                if n:
                    names.add(n)
                if d:
                    descs.add(d)

        korean = sorted(names | descs)
        self.stdout.write(
            f"Scanned {scanned} car(s): {len(names)} unique name(s), "
            f"{len(descs)} unique description(s), {len(korean)} total Korean string(s)."
        )
        if not korean:
            raise CommandError("No optionsChoice strings found — check DATABASE_URL.")

        cache = self._load_cache()

        # ── Stage 1: Korean -> English ──
        ko_en = cache.setdefault("_ko_en", {})
        missing = sorted(s for s in korean if s not in ko_en)
        if missing:
            self.stdout.write(f"Translating {len(missing)} Korean string(s) → en")
            self._translate_batched(missing, "ko", "en", api_key, ko_en)
            self._save_cache(cache)
        else:
            self.stdout.write("Korean→English cache already complete.")

        oc_en = {k: ko_en.get(k, k) for k in korean}
        english = sorted({v for v in oc_en.values() if v and v.strip()})

        # ── Stage 2: English -> ar/es/ru ──
        out = {"en": oc_en}
        for tgt in targets:
            bucket = cache.setdefault(f"_en_{tgt}", {})
            missing = sorted(s for s in english if s not in bucket)
            if missing:
                self.stdout.write(f"Translating {len(missing)} English string(s) → {tgt}")
                self._translate_batched(missing, "en", tgt, api_key, bucket)
                self._save_cache(cache)
            else:
                self.stdout.write(f"English→{tgt} cache already complete.")
            out[tgt] = {e: bucket.get(e, e) for e in english}

        content = json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if opts["dry_run"]:
            self.stdout.write(
                f"[dry-run] would write {OUTPUT_FILE} "
                f"({len(content)} bytes, {len(oc_en)} en / "
                f"{', '.join(f'{len(out[t])} {t}' for t in targets)})"
            )
        else:
            OUTPUT_FILE.write_text(content, encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(
                f"wrote {OUTPUT_FILE.relative_to(settings.BASE_DIR)} "
                f"({len(oc_en)} en + {', '.join(f'{len(out[t])} {t}' for t in targets)})"
            ))

    # ─────── helpers ───────

    def _translate_batched(self, strings, source, target, api_key, bucket):
        for i in range(0, len(strings), BATCH_SIZE):
            chunk = strings[i : i + BATCH_SIZE]
            resp = requests.post(
                GT_URL,
                params={"key": api_key},
                data={"q": chunk, "source": source, "target": target, "format": "text"},
                timeout=30,
            )
            if resp.status_code != 200:
                raise CommandError(
                    f"Google Translate API error {resp.status_code}: {resp.text[:500]}"
                )
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
