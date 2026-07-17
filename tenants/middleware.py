from django.db import connection
from django.http import HttpResponseBadRequest


import re
import time
from collections import defaultdict

from django.db import connection
from django.http import HttpResponseBadRequest, HttpResponseNotFound, HttpResponse


# ── Bots we want to hard-block at the middleware level ──
_BLOCKED_UA_PATTERNS = re.compile(
    r'GPTBot|ChatGPT-User|Google-Extended|CCBot|DotBot|AhrefsBot'
    r'|SemrushBot|MJ12bot|PetalBot|BLEXBot|DataForSeoBot',
    re.IGNORECASE,
)

# Bots we allow but throttle (Googlebot, Bingbot, etc.). ClaudeBot and Meta's
# crawler are AI crawlers that were hitting the filtered /cars/ URLs unthrottled.
_THROTTLED_UA_PATTERNS = re.compile(
    r'Googlebot|GoogleOther|bingbot|Baiduspider|YandexBot'
    r'|ClaudeBot|meta-externalagent|Applebot|Amazonbot',
    re.IGNORECASE,
)

# Parameters that should only contain simple values (no slashes/paths)
_VALID_PAGE_RE = re.compile(r'^\d{1,5}$')
_VALID_ID_RE = re.compile(r'^\d{1,10}$')
_VALID_CAR_TYPE_RE = re.compile(r'^(auction|cars|auctioncars|truck|kbchachacha|japan)?$', re.IGNORECASE)

MAX_PAGE_NUMBER = 200  # Hard cap – no listing needs 200+ pages


class OnDemandTLSCheckMiddleware:
    """Answers Caddy's on-demand-TLS ``ask`` probe: 200 if the requested domain
    is a known tenant domain, 404 otherwise — so Caddy only provisions Let's
    Encrypt certs for real tenants (not any domain someone points at the box).

    Must sit first in MIDDLEWARE: the probe hits an internal host that maps to
    no tenant, so it has to short-circuit before TenantMainMiddleware routes.
    No-op for every other request (and on Railway, which never receives it).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == "/internal/tls-check":
            domain = (request.GET.get("domain") or "").strip().lower().rstrip(".")
            ok = False
            if domain:
                from tenants.models import Domain
                connection.set_schema_to_public()
                ok = Domain.objects.filter(domain=domain).exists()
            return HttpResponse("ok") if ok else HttpResponseNotFound("no")
        return self.get_response(request)


class TrafficCounterMiddleware:
    """Best-effort per-tenant request counters in Redis for the health dashboard.
    One pipelined round-trip per request; wrapped so counting never affects the
    response. Skips static/internal/self paths. Must sit AFTER TenantMainMiddleware
    so connection.schema_name is set."""

    _SKIP = ("/static/", "/media/", "/internal/", "/vps-health/", "/favicon", "/robots")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            p = request.path
            if not any(p.startswith(s) for s in self._SKIP):
                self._count(getattr(connection, "schema_name", "public"))
        except Exception:
            pass
        return self.get_response(request)

    def _count(self, schema):
        import time
        from django_redis import get_redis_connection
        t = time.gmtime()
        minute = time.strftime("%Y%m%d%H%M", t)
        hour = time.strftime("%Y%m%d%H", t)
        day = time.strftime("%Y%m%d", t)
        r = get_redis_connection("default")
        pipe = r.pipeline()
        pipe.incr(f"traf:min:{minute}"); pipe.expire(f"traf:min:{minute}", 7200)          # 2h
        pipe.hincrby(f"traf:hour:{hour}", schema, 1); pipe.expire(f"traf:hour:{hour}", 172800)   # 2d
        pipe.hincrby(f"traf:day:{day}", schema, 1); pipe.expire(f"traf:day:{day}", 2764800)      # 32d
        pipe.execute()


class QueryStringGuardMiddleware:
    """
    Multi-layer request protection:
    1. Block known bad bots entirely
    2. Reject oversized querystrings (> 2 KB)
    3. Validate page / car_type params – reject garbage
    4. Cap page number to MAX_PAGE_NUMBER
    5. Throttle aggressive crawlers
    """
    MAX_QS_LENGTH = 2048  # 2 KB

    # Simple per-IP rate limiting for bots (requests per window)
    BOT_RATE_LIMIT = 10          # max requests
    BOT_RATE_WINDOW = 60         # per 60 seconds
    _bot_hits = defaultdict(list)  # ip -> [timestamps]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        ua = request.META.get('HTTP_USER_AGENT', '')

        # ── 1. Hard-block abusive bots ──
        if _BLOCKED_UA_PATTERNS.search(ua):
            return HttpResponse(
                'Forbidden', status=403, content_type='text/plain',
            )

        # ── 2. Querystring length guard ──
        qs = request.META.get('QUERY_STRING', '')
        if len(qs) > self.MAX_QS_LENGTH:
            return HttpResponseBadRequest(
                'Query string too long.', content_type='text/plain',
            )

        # ── 3 & 4. Validate key GET params on list pages ──
        path = request.path
        if path.rstrip('/') in ('/cars', '/expired-auctions'):
            # Validate page param
            page_val = request.GET.get('page', '')
            if page_val:
                if not _VALID_PAGE_RE.match(page_val):
                    return HttpResponseBadRequest(
                        'Invalid page parameter.', content_type='text/plain',
                    )
                if int(page_val) > MAX_PAGE_NUMBER:
                    return HttpResponseNotFound(
                        'Page not found.', content_type='text/plain',
                    )

            # Validate car_type param (should be 'auction' or 'cars', not a path)
            car_type_val = request.GET.get('car_type', '')
            if car_type_val and not _VALID_CAR_TYPE_RE.match(car_type_val):
                return HttpResponseBadRequest(
                    'Invalid car_type parameter.', content_type='text/plain',
                )

            # Validate numeric ID params
            for param in ('manufacturer', 'model', 'badge', 'color', 'seat_color'):
                val = request.GET.get(param, '')
                if val and not _VALID_ID_RE.match(val):
                    return HttpResponseBadRequest(
                        f'Invalid {param} parameter.', content_type='text/plain',
                    )

        # ── 5. Rate-limit throttled bots ──
        if _THROTTLED_UA_PATTERNS.search(ua):
            ip = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip()
            if not ip:
                ip = request.META.get('REMOTE_ADDR', '')
            now = time.monotonic()
            hits = self._bot_hits[ip]
            # Prune old entries
            hits[:] = [t for t in hits if now - t < self.BOT_RATE_WINDOW]
            if len(hits) >= self.BOT_RATE_LIMIT:
                return HttpResponse(
                    'Rate limited. Please slow down.',
                    status=429, content_type='text/plain',
                )
            hits.append(now)

        return self.get_response(request)


class TenantPublicSchemaMiddleware:
    """
    After TenantMainMiddleware sets the schema, this middleware
    appends 'public' to the search_path so shared apps (like cars)
    are visible from all tenant schemas.

    Optimized: tracks whether the path is already set on this connection
    object to avoid redundant DB round-trips on every request.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tenant = getattr(connection, "tenant", None)
        if tenant and tenant.schema_name != "public":
            # Use a flag on the connection object itself — reset automatically
            # when conn_max_age expires and a new connection is opened.
            if not getattr(connection, "_public_appended", False):
                with connection.cursor() as cursor:
                    cursor.execute("SHOW search_path")
                    current = cursor.fetchone()[0]
                    if "public" not in current:
                        cursor.execute(f"SET search_path TO {current}, public")
                connection._public_appended = True
        return self.get_response(request)


class InactiveTenantMiddleware:
    """Show a clean 'temporarily unavailable' page when a tenant is
    deactivated (Tenant.is_active=False), keeping all of its data intact.

    Staff/superusers bypass the gate so they can still manage the site and
    switch it back on, and the auth/static routes stay open so an admin can
    sign in to reactivate. Runs after AuthenticationMiddleware so that
    request.user is populated.
    """

    # Paths that must stay reachable while the site is off (so staff can log
    # in to flip it back on, and the unavailable page can load its assets).
    _ALLOW_PREFIXES = ("/static/", "/media/", "/login", "/logout", "/accounts/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tenant = getattr(connection, "tenant", None)
        if (
            tenant
            and tenant.schema_name != "public"
            and not getattr(tenant, "is_active", True)
        ):
            user = getattr(request, "user", None)
            if not (user and user.is_authenticated and user.is_staff) and \
               not request.path_info.startswith(self._ALLOW_PREFIXES):
                # Tell crawlers to stop hammering a suspended site (they can't
                # read a 503 robots.txt), so serve an allow-nothing one plainly.
                if request.path_info == "/robots.txt":
                    return HttpResponse(
                        "User-agent: *\nDisallow: /\n", content_type="text/plain",
                    )
                from django.shortcuts import render
                resp = render(
                    request, "tenant_inactive.html", {"tenant": tenant}, status=503,
                )
                resp["Retry-After"] = "86400"  # ask crawlers to back off a day
                # Expected 503 — don't let django.request log it as an ERROR.
                resp._has_been_logged = True
                return resp
        return self.get_response(request)


class BlockTenantAdminMiddleware:
    """Block /admin/ on tenant domains. Only the public (SaaS owner) domain
    can reach Django admin. Tenant staff should use /dashboard/ + /settings/.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path_info
        if path == "/admin" or path.startswith("/admin/"):
            tenant = getattr(connection, "tenant", None)
            if tenant and tenant.schema_name != "public":
                return HttpResponseNotFound(
                    "Not found.", content_type="text/plain"
                )
        return self.get_response(request)
