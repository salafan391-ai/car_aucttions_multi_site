"""
Google Search Console search-analytics for tenant dashboards.

Uses the same service account as gsc_register (env GOOGLE_SA_JSON, webmasters
scope). Results are cached (12h on success, 1h on failure) so the dashboard
reads instantly; a nightly `refresh_gsc` command re-warms the cache.

Note: GOOGLE_SA_JSON may be stored as pretty-printed JSON whose newlines became
literal "\\n" during env migration — _sa_info() parses both that and clean JSON.
"""
import datetime
import json
import os

from django.core.cache import cache

SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
CACHE_TTL_OK = 60 * 60 * 12
CACHE_TTL_FAIL = 60 * 60


def _sa_info():
    raw = os.environ.get("GOOGLE_SA_JSON", "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        # Repair pretty-printed JSON whose newlines became literal "\n", and
        # allow the raw newlines that leaves inside the private_key string.
        return json.loads(raw.replace("\\n", "\n"), strict=False)


def fetch_search_metrics(domain):
    """Live GSC query for one domain (URL-prefix property https://<domain>/)."""
    info = _sa_info()
    if not info:
        return None
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_info(info, scopes=[SCOPE])
    svc = build("searchconsole", "v1", credentials=creds, cache_discovery=False)
    site = f"https://{domain}/"
    end = datetime.date.today()
    start = end - datetime.timedelta(days=28)
    base = {"startDate": str(start), "endDate": str(end)}

    def q(extra):
        body = dict(base)
        body.update(extra)
        return svc.searchanalytics().query(siteUrl=site, body=body).execute().get("rows", [])

    totals = q({})
    t = totals[0] if totals else {}
    queries = q({"dimensions": ["query"], "rowLimit": 10})
    pages = q({"dimensions": ["page"], "rowLimit": 10})
    return {
        "clicks": int(t.get("clicks", 0)),
        "impressions": int(t.get("impressions", 0)),
        "ctr": round(t.get("ctr", 0) * 100, 1),
        "position": round(t.get("position", 0), 1),
        "top_queries": [
            {"q": r["keys"][0], "clicks": int(r["clicks"]), "impressions": int(r["impressions"])}
            for r in queries
        ],
        "top_pages": [
            {"url": r["keys"][0], "clicks": int(r["clicks"]), "impressions": int(r["impressions"])}
            for r in pages
        ],
        "range": f"{start} — {end}",
    }


def get_search_metrics(domain, force=False):
    """Cached GSC metrics for a domain. Returns None if unavailable (site not in
    GSC, no creds, API error). Failures are cached briefly to avoid retry storms."""
    if not domain:
        return None
    key = f"gsc:v1:{domain}"
    if not force:
        cached = cache.get(key)
        if cached is not None:
            return cached or None  # {} sentinel = known-empty/failed
    try:
        data = fetch_search_metrics(domain)
    except Exception:
        data = None
    cache.set(key, data or {}, CACHE_TTL_OK if data else CACHE_TTL_FAIL)
    return data
