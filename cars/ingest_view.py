"""HTTP-triggered ingest from a Cloudflare R2 key.

Replaces `railway run python manage.py import_auction_json ... --r2` so the
car_scraper pipeline doesn't have to run `railway run` from a developer's
Mac (and doesn't have to override DATABASE_URL with the public proxy — this
view runs inside Railway's private network, so postgres.railway.internal
resolves natively).
"""

import json
import os
import threading

from django.core.management import call_command
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST


@csrf_exempt
@require_POST
def ingest_from_r2(request):
    expected_token = os.environ.get("INGEST_TOKEN", "")
    if not expected_token:
        return JsonResponse(
            {"error": "INGEST_TOKEN env var not configured on receiver"},
            status=503,
        )
    if request.headers.get("X-Ingest-Token") != expected_token:
        return JsonResponse({"error": "unauthorized"}, status=401)

    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid JSON body"}, status=400)

    r2_key = (body.get("r2_key") or "").strip()
    if not r2_key:
        return JsonResponse({"error": "r2_key required"}, status=400)
    r2_bucket = (body.get("r2_bucket") or os.environ.get("R2_BUCKET", "")).strip()

    def background_import():
        try:
            args = [r2_key, "--r2"]
            if r2_bucket:
                args += ["--r2-bucket", r2_bucket]
            call_command("import_auction_json", *args)
            print(f"[ingest] import_auction_json OK: {r2_bucket}/{r2_key}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[ingest] import_auction_json FAILED: {r2_bucket}/{r2_key}: {exc}", flush=True)

    threading.Thread(target=background_import, daemon=True).start()
    return JsonResponse(
        {"ok": True, "status": "started", "r2_key": r2_key, "r2_bucket": r2_bucket}
    )
