"""Inject `data-lang-es="{{ X|translate_FOO:'es' }}"` and its `ru` counterpart
next to existing `data-lang-ar="{{ X|translate_FOO }}"` attributes.

This is the Django-filter sibling of `translate_templates`: it handles dynamic
values rendered through the enum-translation filters (translate_color,
translate_fuel, translate_transmission, translate_body, translate_option,
ar_address) so those values localize correctly for Spanish / Russian users.

Idempotent — skips any tag that already has the target attribute.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


TEMPLATES_DIR = Path(settings.BASE_DIR) / "templates"

# Each entry: (filter name in `data-lang-ar`, builder(expr, lang) → new value for data-lang-<lang>).
# The builder receives the Django expression before the pipe (e.g. "car.color.name")
# and returns the new attribute value (without quotes).
ENUM_FILTERS = {
    "translate_color":        lambda expr, lang: f"{{{{ {expr}|translate_color:'{lang}' }}}}",
    "translate_fuel":         lambda expr, lang: f"{{{{ {expr}|translate_fuel:'{lang}' }}}}",
    "translate_transmission": lambda expr, lang: f"{{{{ {expr}|translate_transmission:'{lang}' }}}}",
    "translate_body":         lambda expr, lang: f"{{{{ {expr}|translate_body:'{lang}' }}}}",
    "translate_option":       lambda expr, lang: f"{{{{ {expr}|translate_option:'{lang}' }}}}",
    "translate_model":        lambda expr, lang: f"{{{{ {expr}|translate_model:'{lang}' }}}}",
    "translate_manufacturer": lambda expr, lang: f"{{{{ {expr}|translate_manufacturer:'{lang}' }}}}",
    "ar_address":             lambda expr, lang: f"{{{{ {expr}|translate_address:'{lang}' }}}}",
}


class Command(BaseCommand):
    help = "Add data-lang-es / data-lang-ru attrs next to data-lang-ar that uses an enum filter."

    def add_arguments(self, parser):
        parser.add_argument("--target", default="es,ru")
        parser.add_argument("--paths", default=str(TEMPLATES_DIR))
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        targets = [t.strip() for t in opts["target"].split(",") if t.strip()]
        root = Path(opts["paths"])
        dry = opts["dry_run"]

        files = list(root.rglob("*.html"))
        self.stdout.write(f"Scanning {len(files)} template(s) under {root}")

        modified = 0
        for path in files:
            original = path.read_text(encoding="utf-8")
            content = original
            for filt, builder in ENUM_FILTERS.items():
                for tgt in targets:
                    content = self._inject(content, filt, builder, tgt)
            if content != original:
                modified += 1
                if dry:
                    self.stdout.write(f"[dry-run] would update {path.relative_to(settings.BASE_DIR)}")
                else:
                    path.write_text(content, encoding="utf-8")
                    self.stdout.write(self.style.SUCCESS(
                        f"updated {path.relative_to(settings.BASE_DIR)}"
                    ))

        verb = "would update" if dry else "updated"
        self.stdout.write(self.style.SUCCESS(f"Done. {verb} {modified} file(s)."))

    def _inject(self, content: str, filter_name: str, builder, target: str) -> str:
        target_attr = f"data-lang-{target}"
        # Match   data-lang-ar="{{ <EXPR>|<filter_name> }}"   where the tag
        # does not already contain the target attribute (scoped via [^<>]).
        # <EXPR> allows dots, pipes, filter arguments like `:'ar'`, and nested
        # Django filters — anything that isn't a quote or pipe-then-filter-name.
        pattern = re.compile(
            rf'data-lang-ar="\{{\{{\s*([^"}}]+?)\s*\|\s*{re.escape(filter_name)}\s*\}}\}}"'
            rf'(?![^<>]*{re.escape(target_attr)}=)'
        )

        def repl(m: re.Match[str]) -> str:
            expr = m.group(1).strip()
            new_val = builder(expr, target)
            # Preserve the original data-lang-ar, then append the new attr.
            return f'{m.group(0)} {target_attr}="{new_val}"'

        return pattern.sub(repl, content)
