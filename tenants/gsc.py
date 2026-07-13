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
    """Live GSC query for one domain (URL-prefix property https://<domain>/).
    Returns totals + 28-day-vs-previous deltas, top queries, top pages,
    'opportunity' queries (ranking 5-15 = almost page 1), and a daily sparkline."""
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
    prev_end = start - datetime.timedelta(days=1)
    prev_start = prev_end - datetime.timedelta(days=27)
    cur = {"startDate": str(start), "endDate": str(end)}
    prev = {"startDate": str(prev_start), "endDate": str(prev_end)}

    def q(body):
        return svc.searchanalytics().query(siteUrl=site, body=body).execute().get("rows", [])

    trow = q(cur)
    t = trow[0] if trow else {}
    prow = q(prev)
    p = prow[0] if prow else {}
    queries = q({**cur, "dimensions": ["query"], "rowLimit": 100})
    pages = q({**cur, "dimensions": ["page"], "rowLimit": 10})
    daily = q({**cur, "dimensions": ["date"], "rowLimit": 60})

    def pct(a, b):
        return round(100 * (a - b) / b) if b else None

    cur_clicks, cur_impr = int(t.get("clicks", 0)), int(t.get("impressions", 0))
    prev_clicks, prev_impr = int(p.get("clicks", 0)), int(p.get("impressions", 0))

    top_queries = [
        {"q": r["keys"][0], "clicks": int(r["clicks"]), "impressions": int(r["impressions"])}
        for r in sorted(queries, key=lambda r: -r.get("clicks", 0))[:10]
    ]
    opportunities = [
        {"q": r["keys"][0], "impressions": int(r["impressions"]), "position": round(r.get("position", 0), 1)}
        for r in sorted(
            [r for r in queries if 5 <= r.get("position", 0) <= 15 and r.get("impressions", 0) >= 5],
            key=lambda r: -r.get("impressions", 0),
        )[:8]
    ]
    series = [int(r.get("clicks", 0)) for r in sorted(daily, key=lambda r: r["keys"][0])]
    mx = max(series) if series else 0
    spark = [round(100 * v / mx) if mx else 0 for v in series]

    return {
        "clicks": cur_clicks,
        "impressions": cur_impr,
        "ctr": round(t.get("ctr", 0) * 100, 1),
        "position": round(t.get("position", 0), 1),
        "clicks_delta": pct(cur_clicks, prev_clicks),
        "impr_delta": pct(cur_impr, prev_impr),
        "top_queries": top_queries,
        "opportunities": opportunities,
        "top_pages": [
            {"url": r["keys"][0], "clicks": int(r["clicks"]), "impressions": int(r["impressions"])}
            for r in pages
        ],
        "spark": spark,
        "range": f"{start} — {end}",
    }


def get_search_metrics(domain, force=False):
    """Cached GSC metrics for a domain. Returns None if unavailable (site not in
    GSC, no creds, API error). Failures are cached briefly to avoid retry storms."""
    if not domain:
        return None
    key = f"gsc:v2:{domain}"
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
