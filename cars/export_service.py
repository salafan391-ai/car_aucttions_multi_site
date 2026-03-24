"""
PDF Export Service — webhook-based (no polling threads).

Flow
────
  1. start_export(entries, auction_name, webhook_url)
       POST /api/auth/token/      → obtain token
       POST /api/exports/         → create job; ofleet will POST back to webhook_url
       Returns (token, job_id)    immediately — NO polling

  2. ofleet calls YOUR /webhook/ofleet/ endpoint when the job is done.
     The webhook view calls process_webhook_payload(data, schema_name, parent_export_id).

  3. process_webhook_payload downloads each PDF and saves a PdfExport record per make.

Public API
──────────
  start_export(entries, auction_name, webhook_url)  → (token, job_id)
  process_webhook_payload(data, schema_name, ...)   → None  (saves DB records)
  download_pdf(token, file_id_or_url)               → bytes

  run_export_job(...)  — DEPRECATED shim, does nothing (kept so old imports don't break)

Credentials come from the Tenant model (ofleet_username / ofleet_password)
with a fallback to settings.OFLEET_USERNAME / OFLEET_PASSWORD.
"""

import logging
import requests
from django.conf import settings
from django.db import connection

logger = logging.getLogger(__name__)

BASE_URL = getattr(settings, 'OFLEET_API_BASE', 'https://ofleet0.com')


# ─────────────────────────────────────────────────────────────────────────────
# Credential resolution
# ─────────────────────────────────────────────────────────────────────────────

def _get_credentials():
    tenant = getattr(connection, 'tenant', None)
    if tenant is not None:
        username = getattr(tenant, 'ofleet_username', '') or ''
        password = getattr(tenant, 'ofleet_password', '') or ''
        if username and password:
            return username, password
    username = getattr(settings, 'OFLEET_USERNAME', '')
    password = getattr(settings, 'OFLEET_PASSWORD', '')
    return username, password


def _auth_headers(token):
    return {'Authorization': f'Token {token}'}


# ─────────────────────────────────────────────────────────────────────────────
# Step helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_token():
    username, password = _get_credentials()
    resp = requests.post(
        f"{BASE_URL}/api/auth/token/",
        json={'username': username, 'password': password},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data.get('token') or data.get('access') or data.get('auth_token')
    if not token:
        raise ValueError(f"No token in auth response: {data}")
    return token


def _create_job(token, entries, auction_name, webhook_url):
    """Create the export job on ofleet, passing our webhook URL so they call us back."""
    tenant = getattr(connection, 'tenant', None)
    split_by_make = getattr(tenant, 'ofleet_split_by_make', True)  # default True

    resp = requests.post(
        f"{BASE_URL}/api/exports/",
        json={
            'entries': entries,
            'auction_name': auction_name,
            'split_by_make': split_by_make,
            'webhook_url': webhook_url,
        },
        headers=_auth_headers(token),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _fetch_job(token, job_id):
    resp = requests.get(
        f"{BASE_URL}/api/exports/{job_id}/",
        headers=_auth_headers(token),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def start_export(entries, auction_name, webhook_url):
    """
    Authenticate with ofleet and submit the export job.

    ofleet will POST to `webhook_url` when the job is done — no polling needed.
    Returns (token, job_id) immediately.

    Raises ValueError  — missing credentials or bad API response
    Raises HTTPError   — network / API errors
    """
    username, password = _get_credentials()
    if not username or not password:
        raise ValueError(
            "No ofleet credentials configured for this tenant. "
            "Set ofleet_username and ofleet_password on the Tenant record in the admin."
        )

    logger.info(
        "Starting export: auction=%s, %d entries, webhook=%s",
        auction_name, len(entries), webhook_url,
    )
    token = _get_token()
    job   = _create_job(token, entries, auction_name, webhook_url)
    job_id = job.get('id')
    if not job_id:
        raise ValueError(f"No 'id' in export creation response: {job}")
    logger.info("Export job created: id=%s", job_id)
    return token, str(job_id)


def download_pdf(token, file_id_or_url):
    """
    Download a PDF from ofleet and return raw bytes.

    Accepts either a full download URL or a numeric file_id.
    """
    if str(file_id_or_url).startswith('http'):
        url = file_id_or_url
    else:
        url = f"{BASE_URL}/api/exports/files/{file_id_or_url}/download/"

    resp = requests.get(
        url,
        headers=_auth_headers(token),
        timeout=120,
        stream=True,
    )
    resp.raise_for_status()
    return resp.content


def process_webhook_payload(data, schema_name, parent_export_id=None):
    """
    Call this from the webhook view when ofleet POSTs a completion notification.

    ofleet webhook payload shape:
        {
            "job_id":   146,
            "status":   "done",      # or "failed"
            "files":    [
                {"label": "Hyundai", "download_url": "https://ofleet0.com/..."}
            ],
            "error_msg": null
        }

    If ofleet sends `groups` (list of make names) instead of `files`, we fetch
    the full job details from /api/exports/{job_id}/ to get the download links.

    For each file: downloads the PDF and saves a PdfExport record.
    If `parent_export_id` is given, the first record reuses that pending row;
    subsequent makes create new rows.
    """
    from django.core.files.base import ContentFile
    from cars.models import PdfExport

    job_id    = data.get('job_id') or data.get('id')
    status    = (data.get('status') or '').lower()
    files     = data.get('files') or []
    error_msg = data.get('error_msg') or data.get('error') or ''

    logger.info(
        "Webhook: job_id=%s status=%s files=%d raw_data=%s schema=%s",
        job_id, status, len(files), data, schema_name,
    )

    # ── Failed job ─────────────────────────────────────────────────────────
    if status in ('failed', 'error'):
        if parent_export_id:
            PdfExport.objects.filter(pk=parent_export_id).update(
                status=PdfExport.STATUS_FAILED,
                error_detail=error_msg or f'Job {job_id} failed on ofleet side',
            )
        else:
            logger.warning("Webhook: job %s failed, no parent record to update", job_id)
        return

    # ── Unexpected status ──────────────────────────────────────────────────
    if status not in ('done', 'completed', 'complete', 'finished'):
        logger.warning("Webhook: unexpected status '%s' for job %s — ignoring", status, job_id)
        return

    # Re-authenticate (needed whether we use files directly or re-fetch the job)
    try:
        token = _get_token()
    except Exception as exc:
        logger.exception("Webhook: failed to get auth token: %s", exc)
        if parent_export_id:
            PdfExport.objects.filter(pk=parent_export_id).update(
                status=PdfExport.STATUS_FAILED,
                error_detail=f'Download auth failed: {exc}',
            )
        return

    # ── If no `files` list, fetch the full job record to get download URLs ─
    if not files and job_id:
        logger.info("Webhook: no files in payload, fetching job %s from API", job_id)
        try:
            resp = requests.get(
                f"{BASE_URL}/api/exports/{job_id}/",
                headers=_auth_headers(token),
                timeout=15,
            )
            resp.raise_for_status()
            job_data = resp.json()
            logger.info("Webhook: fetched job data: %s", job_data)
            files = job_data.get('files') or []
        except Exception as exc:
            logger.exception("Webhook: failed to fetch job %s: %s", job_id, exc)

    # ── Still no files after re-fetch ─────────────────────────────────────
    if not files:
        logger.error("Webhook: job %s done but no files found anywhere", job_id)
        if parent_export_id:
            PdfExport.objects.filter(pk=parent_export_id).update(
                status=PdfExport.STATUS_FAILED,
                error_detail='Job completed but no downloadable files found',
            )
        return

    # Retrieve parent record for auction_name / entry_count metadata
    parent = None
    if parent_export_id:
        try:
            parent = PdfExport.objects.get(pk=parent_export_id)
        except PdfExport.DoesNotExist:
            pass

    for idx, file_info in enumerate(files):
        download_url = file_info.get('download_url') or file_info.get('url')
        file_id      = file_info.get('id') or file_info.get('file_id')
        make_name    = (
            file_info.get('label')
            or file_info.get('make')
            or file_info.get('group')
            or file_info.get('manufacturer')
            or f'group_{idx + 1}'
        )

        # First file reuses the parent record; extras get new rows
        if idx == 0 and parent:
            record           = parent
            record.make_name = make_name
        else:
            record = PdfExport(
                auction_name=parent.auction_name if parent else f'job_{job_id}',
                make_name=make_name,
                schema_name=schema_name,
                entry_count=parent.entry_count if parent else 0,
                status=PdfExport.STATUS_PENDING,
            )
            record.save()

        try:
            ref = download_url or file_id
            if not ref:
                raise ValueError(f"No download_url or id in file payload: {file_info}")

            pdf_bytes    = download_pdf(token, ref)
            auction_safe = (record.auction_name or 'export').replace(' ', '_')
            make_safe    = make_name.replace(' ', '_').replace('/', '-')
            filename     = f"{auction_safe}_{make_safe}_{record.pk}.pdf"

            record.pdf_file.save(filename, ContentFile(pdf_bytes), save=False)
            record.status = PdfExport.STATUS_COMPLETE
            record.save(update_fields=['make_name', 'pdf_file', 'status'])
            logger.info("PdfExport %d (%s) saved: %s", record.pk, make_name, filename)

        except Exception as exc:
            logger.exception(
                "Webhook: PdfExport %d (%s) download failed: %s",
                record.pk, make_name, exc,
            )
            record.status       = PdfExport.STATUS_FAILED
            record.error_detail = str(exc)
            record.save(update_fields=['make_name', 'status', 'error_detail'])


# ─────────────────────────────────────────────────────────────────────────────
# Backwards-compat shim — old callers won't crash
# ─────────────────────────────────────────────────────────────────────────────

def run_export_job(export_id, token, job_id):  # noqa: ARG001
    """DEPRECATED — the webhook flow no longer uses polling threads."""
    logger.warning(
        "run_export_job() is deprecated — use the webhook flow "
        "(process_webhook_payload) instead."
    )


def check_export(token, job_id):  # noqa: ARG001
    """DEPRECATED — retained for any existing imports."""
    logger.warning("check_export() is deprecated — ofleet now calls your webhook.")
    return {'status': 'pending'}
