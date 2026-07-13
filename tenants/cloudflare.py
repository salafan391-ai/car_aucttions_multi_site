"""
Point a tenant domain at the self-hosted VPS by setting its Cloudflare DNS
record via the API, so activating a domain is one click in admin instead of
manual Cloudflare edits. Caddy then issues the TLS cert on-demand on first hit.

Requires env CLOUDFLARE_API_TOKEN (scoped: Zone → DNS → Edit, Zone → Read).
Target IP defaults to env VPS_IP, else the box IP below. Inert (raises a clear
error) until the token is present, so shipping this without the token is safe.
"""
import os

import requests

CF_API = "https://api.cloudflare.com/client/v4"
DEFAULT_VPS_IP = "142.132.232.37"
_TIMEOUT = 15


class CloudflareError(RuntimeError):
    pass


def _headers():
    token = os.environ.get("CLOUDFLARE_API_TOKEN")
    if not token:
        raise CloudflareError("CLOUDFLARE_API_TOKEN is not set — add it to the server .env")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _get(path, **params):
    r = requests.get(f"{CF_API}{path}", headers=_headers(), params=params, timeout=_TIMEOUT)
    data = r.json()
    if not data.get("success"):
        raise CloudflareError(f"GET {path} failed: {data.get('errors')}")
    return data["result"]


def _find_zone(domain):
    """(zone_id, zone_name) for the domain's registrable zone. Walks up labels so
    a subdomain (demo.ofleet0.com) resolves to its parent zone (ofleet0.com)."""
    labels = domain.split(".")
    for i in range(len(labels) - 1):
        candidate = ".".join(labels[i:])
        zones = _get("/zones", name=candidate)
        if zones:
            return zones[0]["id"], candidate
    raise CloudflareError(f"No Cloudflare zone found for {domain} (is it in this account?)")


def point_domain_to_vps(domain, ip=None):
    """Create/replace the A record for `domain` → the VPS, DNS-only (grey cloud).
    Idempotent: removes any existing A/AAAA/CNAME at that exact name first.
    Returns a short human-readable status string; raises CloudflareError on failure."""
    domain = (domain or "").strip().lower().rstrip(".")
    if not domain:
        raise CloudflareError("empty domain")
    ip = ip or os.environ.get("VPS_IP") or DEFAULT_VPS_IP
    zone_id, zone_name = _find_zone(domain)

    # Clear any conflicting record at this exact name (old CNAME → Railway, etc.).
    removed = 0
    for rec in _get(f"/zones/{zone_id}/dns_records", name=domain):
        if rec["type"] in ("A", "AAAA", "CNAME"):
            dr = requests.delete(
                f"{CF_API}/zones/{zone_id}/dns_records/{rec['id']}",
                headers=_headers(), timeout=_TIMEOUT,
            )
            if dr.json().get("success"):
                removed += 1

    r = requests.post(
        f"{CF_API}/zones/{zone_id}/dns_records",
        headers=_headers(), timeout=_TIMEOUT,
        json={"type": "A", "name": domain, "content": ip, "proxied": False, "ttl": 1},
    )
    data = r.json()
    if not data.get("success"):
        raise CloudflareError(f"Create A record failed: {data.get('errors')}")
    return f"{domain} → {ip} (zone {zone_name}, DNS-only; replaced {removed} old record(s))"
