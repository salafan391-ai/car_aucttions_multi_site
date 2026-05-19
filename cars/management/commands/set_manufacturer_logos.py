"""
Set Manufacturer.logo for every row whose name matches an entry in the brand-logo
mapping JSON. Names are lowercased + stripped on both sides before matching, since
the DB stores manufacturer.name in normalized lowercase form.

Default JSON is `cars/data/brand_logos.json` (185 brands → S3 SVG URLs). Pass a
different path with `--json /abs/path.json` if you want to point at another source.

Usage:
    python manage.py set_manufacturer_logos           # dry-run (default)
    python manage.py set_manufacturer_logos --apply   # write changes
"""

import json
import re
import unicodedata
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from cars.models import Manufacturer


DEFAULT_JSON = Path(settings.BASE_DIR) / "cars" / "data" / "brand_logos.json"

_NONALPHA_RE = re.compile(r"[^a-z0-9]")
_TOKEN_SPLIT_RE = re.compile(r"[\s\-_()]+")


def _strip_diacritics(s):
    # 'citroën' → 'citroen', 'café' → 'cafe'. NFD decomposes accented chars,
    # then we drop the combining marks.
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _norm(s):
    return _strip_diacritics((s or "").strip()).lower()


def _strip_norm(s):
    """Aggressive form for fallback matching: strip every non-alphanumeric so
    `astonmartin` matches `aston martin`, `rolls-royce` matches `rollsroyce`,
    etc. Used only when the exact-lower lookup misses."""
    return _NONALPHA_RE.sub("", _norm(s))


def _tokens(s):
    """Split on whitespace/hyphen/underscore/paren so we can try first-token
    lookups for compound names like `man truck`, `daewoo bus`, `baic yinxiang`."""
    return [t for t in _TOKEN_SPLIT_RE.split(_norm(s)) if t]


class Command(BaseCommand):
    help = "Set Manufacturer.logo from a brand_logos.json mapping."

    def add_arguments(self, parser):
        parser.add_argument(
            "--json",
            default=str(DEFAULT_JSON),
            help=f"Path to the brand-logo JSON file. Default: {DEFAULT_JSON}",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write changes. Default is dry-run.",
        )
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Replace existing logo URLs. Default leaves rows that already have a logo alone.",
        )

    def handle(self, *args, **options):
        path = Path(options["json"])
        if not path.exists():
            raise CommandError(f"JSON file not found: {path}")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise CommandError(f"Invalid JSON in {path}: {e}")
        if not isinstance(raw, dict):
            raise CommandError("JSON must be an object mapping brand → URL.")

        # Build two lookup maps: exact-lower (preferred) and aggressive strip
        # (fallback). Aggressive map collisions are kept first-wins so we don't
        # accidentally clobber a clean key.
        logos = {_norm(k): v for k, v in raw.items() if k and v}
        logos_strip = {}
        for k, v in raw.items():
            if not k or not v:
                continue
            sk = _strip_norm(k)
            logos_strip.setdefault(sk, v)

        apply_changes = options["apply"]
        overwrite = options["overwrite"]

        mode = self.style.SUCCESS("APPLY") if apply_changes else self.style.WARNING("DRY-RUN")
        self.stdout.write(f"=== set_manufacturer_logos — mode={mode}, source={path.name} ===")
        self.stdout.write(f"  {len(logos)} brand entries in JSON")

        matched = []
        skipped_has_logo = []
        unmatched = []
        for m in Manufacturer.objects.all().order_by("name"):
            url = logos.get(_norm(m.name)) or logos_strip.get(_strip_norm(m.name))
            # Token fallback for compound names like 'man truck', 'daewoo bus',
            # 'baic yinxiang'. Try each token in order — first token wins.
            if not url:
                for tok in _tokens(m.name):
                    url = logos.get(tok) or logos_strip.get(tok)
                    if url:
                        break
            if not url:
                unmatched.append(m)
                continue
            if m.logo and not overwrite:
                skipped_has_logo.append((m, url))
                continue
            matched.append((m, url))

        for m, url in matched:
            self.stdout.write(f"  ✓ {m.name} → {url}")
            if apply_changes:
                Manufacturer.objects.filter(id=m.id).update(logo=url)

        if skipped_has_logo:
            self.stdout.write(self.style.NOTICE(
                f"\n  {len(skipped_has_logo)} row(s) already have a logo (pass --overwrite to replace)"
            ))
        if unmatched:
            self.stdout.write(self.style.WARNING(
                f"\n  {len(unmatched)} Manufacturer rows had no matching JSON entry:"
            ))
            for m in unmatched:
                self.stdout.write(f"      {m.name}")

        verb = "updated" if apply_changes else "would update"
        self.stdout.write(self.style.SUCCESS(f"\n→ {verb} {len(matched)} manufacturer logo(s)."))
        if not apply_changes:
            self.stdout.write(self.style.WARNING("Dry-run complete. Re-run with --apply to commit."))
