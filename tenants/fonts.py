"""Per-tenant site font catalogue.

One source of truth for both the model field choices (admin/site-settings
dropdown) and the runtime context (Google Fonts URL + CSS family stack that
the base templates inject). All families support Arabic + Latin so a single
choice styles the whole site regardless of the active language.
"""

# key -> label (admin) + Google Fonts family spec + CSS font stack
SITE_FONTS = {
    "cairo":       {"label": "Cairo — كايرو",            "family": "Cairo:wght@400;500;600;700;800",            "stack": "'Cairo', sans-serif"},
    "tajawal":     {"label": "Tajawal — طجوال",          "family": "Tajawal:wght@400;500;700;800",              "stack": "'Tajawal', sans-serif"},
    "almarai":     {"label": "Almarai — المراعي",        "family": "Almarai:wght@300;400;700;800",              "stack": "'Almarai', sans-serif"},
    "el-messiri":  {"label": "El Messiri — المسيري",      "family": "El+Messiri:wght@400;500;600;700",           "stack": "'El Messiri', sans-serif"},
    "changa":      {"label": "Changa — تشانغا",          "family": "Changa:wght@400;500;600;700;800",           "stack": "'Changa', sans-serif"},
    "readex-pro":  {"label": "Readex Pro — ريدكس",        "family": "Readex+Pro:wght@400;500;600;700",           "stack": "'Readex Pro', sans-serif"},
    "noto-kufi":   {"label": "Noto Kufi — نوتو كوفي",     "family": "Noto+Kufi+Arabic:wght@400;500;700;800",     "stack": "'Noto Kufi Arabic', sans-serif"},
    "ibm-plex-ar": {"label": "IBM Plex Arabic",          "family": "IBM+Plex+Sans+Arabic:wght@400;500;600;700", "stack": "'IBM Plex Sans Arabic', sans-serif"},
    "rubik":       {"label": "Rubik — روبيك",            "family": "Rubik:wght@400;500;600;700;800",            "stack": "'Rubik', sans-serif"},
    "markazi":     {"label": "Markazi — مركزي",          "family": "Markazi+Text:wght@400;500;600;700",         "stack": "'Markazi Text', serif"},
    # System font (no Google Fonts download) — Tahoma has solid Arabic glyphs.
    "tahoma":      {"label": "Tahoma — تاهوما",          "family": None,                                        "stack": "Tahoma, 'Segoe UI', Geneva, Verdana, sans-serif"},
}


def font_choices():
    """Choices for the Tenant.site_font field (blank = use the theme's own font)."""
    return [("", "افتراضي الثيم (Theme default)")] + [(k, v["label"]) for k, v in SITE_FONTS.items()]


def font_url(family):
    return f"https://fonts.googleapis.com/css2?family={family}&display=swap"


def font_ctx(tenant):
    """Template context for the chosen site font (empty when none is set)."""
    key = (getattr(tenant, "site_font", "") or "").strip()
    f = SITE_FONTS.get(key)
    if not f:
        return {"site_font_url": "", "site_font_stack": ""}
    # System fonts have no `family` → no Google Fonts <link>, just the stack.
    url = font_url(f["family"]) if f.get("family") else ""
    return {"site_font_url": url, "site_font_stack": f["stack"]}
