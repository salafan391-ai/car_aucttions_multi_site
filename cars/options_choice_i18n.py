"""Translated Encar ``optionsChoice`` strings, loaded from the sibling
``options_choice_i18n.json`` produced by ``python manage.py translate_options_choice``.

``OC_EN`` maps a Korean source string -> English (the canonical display text).
``OC_AR`` / ``OC_RU`` / ``OC_ES`` map an *English* string -> that language, so
Korean -> ar/ru/es is a two-hop lookup (ko -> en -> lang). This mirrors the
English-pivot pattern already used by ``translate_enums`` / ``cars/utils_i18n.py``.

The lookups degrade gracefully: a missing key falls back to the source string,
so the detail page shows Korean until the translation command has been run.
"""

from __future__ import annotations

import json
from pathlib import Path

_JSON = Path(__file__).with_name("options_choice_i18n.json")

try:
    _data = json.loads(_JSON.read_text(encoding="utf-8"))
except (OSError, ValueError):
    _data = {}

OC_EN = _data.get("en", {})   # korean  -> english
OC_AR = _data.get("ar", {})   # english -> arabic
OC_RU = _data.get("ru", {})   # english -> russian
OC_ES = _data.get("es", {})   # english -> spanish
