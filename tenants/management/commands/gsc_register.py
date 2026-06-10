"""Register every tenant domain with Google Search Console:
verify ownership (meta-tag method) -> add the URL-prefix property -> submit
/sitemap.xml.

Setup (one-time):
  * Google Cloud project with the **Site Verification API** and **Google Search
    Console API** enabled, and a **service account** (JSON key).
  * Put the JSON key contents in the env var GOOGLE_SA_JSON (single line or
    escaped) — e.g. on Railway.

Run on PRODUCTION (the domains must resolve and serve the verification meta tag):
    railway ssh "python manage.py gsc_register"
    railway ssh "python manage.py gsc_register --domain huna-korea.com"
    railway ssh "python manage.py gsc_register --dry-run"
"""
import json
import os
import time

from django.core.cache import cache
from django.core.management.base import BaseCommand

from tenants.models import Domain

SCOPES = [
    "https://www.googleapis.com/auth/siteverification",
    "https://www.googleapis.com/auth/webmasters",
]
# Domains that aren't real public sites — skip them.
SKIP = {"localhost", "127.0.0.1"}


def _is_skippable(domain: str) -> bool:
    d = (domain or "").lower()
    return (not d) or d in SKIP or d.endswith(".railway.app") or d.endswith(".up.railway.app")


class Command(BaseCommand):
    help = "Verify + register every tenant domain in Google Search Console and submit its sitemap."

    def add_arguments(self, parser):
        parser.add_argument("--domain", help="Only process this one domain.")
        parser.add_argument("--dry-run", action="store_true", help="Show what would happen; no API calls that change state.")

    def handle(self, *args, **opts):
        raw = os.environ.get("GOOGLE_SA_JSON", "").strip()
        if not raw:
            self.stderr.write("GOOGLE_SA_JSON is not set — add the service-account JSON key to the env first.")
            return
        try:
            info = json.loads(raw)
        except json.JSONDecodeError as e:
            self.stderr.write(f"GOOGLE_SA_JSON is not valid JSON: {e}")
            return

        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError

        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        sv = build("siteVerification", "v1", credentials=creds, cache_discovery=False)
        sc = build("searchconsole", "v1", credentials=creds, cache_discovery=False)

        only = (opts.get("domain") or "").lower().strip()
        dry = opts.get("dry_run")

        domains = []
        for dom in Domain.objects.select_related("tenant").all():
            name = (dom.domain or "").lower()
            if _is_skippable(name):
                continue
            if only and name != only:
                continue
            domains.append(dom)

        if not domains:
            self.stdout.write("No matching domains.")
            return

        for dom in domains:
            name = dom.domain.lower()
            site_url = f"https://{name}/"
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n== {name} =="))
            try:
                # 1) Get the FILE verification token (a filename like
                #    "google<hash>.html"). Served from a dedicated, never-cached
                #    endpoint — so verification never races the home-page cache.
                token_resp = sv.webResource().getToken(body={
                    "verificationMethod": "FILE",
                    "site": {"type": "SITE", "identifier": site_url},
                }).execute()
                content = token_resp.get("token", "")  # e.g. "google1a2b3c.html"
                self.stdout.write(f"   file: /{content}")

                if dry:
                    self.stdout.write("   (dry-run) would save token, verify, add property, submit sitemap.")
                    continue

                # Persist on the tenant — the /<file>.html view reads it fresh (uncached).
                tenant = dom.tenant
                tenant.gsc_verification_token = content
                tenant.save(update_fields=["gsc_verification_token"])
                time.sleep(2)  # ensure the saved token is visible to Google's fetch

                # 2) Verify ownership — Google fetches /<file>.html and checks its content.
                sv.webResource().insert(verificationMethod="FILE", body={
                    "site": {"type": "SITE", "identifier": site_url},
                }).execute()
                self.stdout.write(self.style.SUCCESS("   ✓ verified"))

                # 3) Add the URL-prefix property + submit the sitemap.
                try:
                    sc.sites().add(siteUrl=site_url).execute()
                except HttpError as e:
                    self.stdout.write(f"   sites.add: {e.resp.status} (often already added)")
                sitemap_url = f"https://{name}/sitemap.xml"
                sc.sitemaps().submit(siteUrl=site_url, feedpath=sitemap_url).execute()
                self.stdout.write(self.style.SUCCESS(f"   ✓ sitemap submitted: {sitemap_url}"))

            except HttpError as e:
                self.stderr.write(f"   API error: {getattr(e, 'status_code', '')} {e}")
            except Exception as e:
                self.stderr.write(f"   failed: {e}")

        self.stdout.write(self.style.SUCCESS("\nDone."))
