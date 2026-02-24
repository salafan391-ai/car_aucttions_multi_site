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

# Bots we allow but throttle (Googlebot, Bingbot, etc.)
_THROTTLED_UA_PATTERNS = re.compile(
    r'Googlebot|GoogleOther|bingbot|Baiduspider|YandexBot',
    re.IGNORECASE,
)

# Parameters that should only contain simple values (no slashes/paths)
_VALID_PAGE_RE = re.compile(r'^\d{1,5}$')
_VALID_ID_RE = re.compile(r'^\d{1,10}$')
_VALID_CAR_TYPE_RE = re.compile(r'^(auction|cars|auctioncars)?$', re.IGNORECASE)

MAX_PAGE_NUMBER = 200  # Hard cap – no listing needs 200+ pages


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
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tenant = getattr(connection, "tenant", None)
        if tenant and tenant.schema_name != "public":
            cursor = connection.cursor()
            cursor.execute("SHOW search_path")
            current = cursor.fetchone()[0]
            if "public" not in current:
                cursor.execute(f"SET search_path TO {current}, public")
        return self.get_response(request)
