"""
Live VPS health/metrics dashboard for the SaaS owner.

Superuser-only, public-schema (owner domain) only — served at /vps-health/.
Pulls the same numbers we'd check by hand: load, memory, disk, service status,
Postgres, Redis, tenant counts, next import. Every metric is best-effort so one
failing probe never breaks the page.
"""
import os
import shutil
import subprocess
import time

from django.contrib.admin.views.decorators import staff_member_required
from django.db import connection
from django.http import HttpResponseNotFound
from django.shortcuts import render


def _svc(name):
    try:
        r = subprocess.run(["systemctl", "is-active", name],
                           capture_output=True, text=True, timeout=3)
        return (r.stdout.strip() or "unknown")
    except Exception:
        return "unknown"


def _meminfo():
    d = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                k, _, v = line.partition(":")
                d[k.strip()] = int(v.strip().split()[0])  # kB
    except Exception:
        pass
    return d


@staff_member_required
def vps_health(request):
    # Owner (public) schema only — 404 on tenant domains.
    if getattr(connection, "schema_name", "public") != "public":
        return HttpResponseNotFound("Not found.")

    ctx = {"now": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())}

    # ── CPU / load / uptime ──
    try:
        la = os.getloadavg()
        cores = os.cpu_count() or 1
        ctx["load"] = [round(x, 2) for x in la]
        ctx["cores"] = cores
        ctx["load_pct"] = round(100 * la[0] / cores)
    except Exception:
        pass
    try:
        with open("/proc/uptime") as f:
            up = float(f.read().split()[0])
        dd, rem = divmod(int(up), 86400)
        hh, rem = divmod(rem, 3600)
        mm, _ = divmod(rem, 60)
        ctx["uptime"] = f"{dd}d {hh}h {mm}m"
    except Exception:
        pass

    # ── Memory / swap ──
    mi = _meminfo()
    if mi:
        total, avail = mi.get("MemTotal", 0), mi.get("MemAvailable", 0)
        used = total - avail
        ctx["mem"] = {
            "total_gb": round(total / 1048576, 1),
            "used_gb": round(used / 1048576, 1),
            "cache_gb": round((mi.get("Cached", 0) + mi.get("Buffers", 0)) / 1048576, 1),
            "pct": round(100 * used / total) if total else 0,
        }
        st, sf = mi.get("SwapTotal", 0), mi.get("SwapFree", 0)
        ctx["swap"] = {"used_mb": round((st - sf) / 1024), "total_mb": round(st / 1024)}

    # ── Disk ──
    try:
        du = shutil.disk_usage("/")
        ctx["disk"] = {
            "total_gb": round(du.total / 1e9),
            "used_gb": round(du.used / 1e9),
            "free_gb": round(du.free / 1e9),
            "pct": round(100 * du.used / du.total),
        }
    except Exception:
        pass

    # ── Services ──
    ctx["services"] = {
        n: _svc(n) for n in
        ["caddy", "tenant", "postgresql@18-main", "redis-server", "tenant-import.timer"]
    }

    # ── Postgres ──
    try:
        with connection.cursor() as c:
            c.execute("select pg_size_pretty(pg_database_size(current_database()))")
            ctx["pg_size"] = c.fetchone()[0]
            c.execute("select round(100.0*sum(heap_blks_hit)/nullif(sum(heap_blks_hit)+sum(heap_blks_read),0),2) "
                      "from pg_statio_user_tables")
            ctx["pg_cache_hit"] = c.fetchone()[0]
            c.execute("select count(*), count(*) filter (where state='active'), current_setting('max_connections') "
                      "from pg_stat_activity")
            row = c.fetchone()
            ctx["pg_conns"] = {"total": row[0], "active": row[1], "max": row[2]}
    except Exception:
        pass

    # ── Redis ──
    try:
        from django_redis import get_redis_connection
        info = get_redis_connection("default").info()
        hits, misses = info.get("keyspace_hits", 0), info.get("keyspace_misses", 0)
        db0 = info.get("db0") or {}
        mx = int(info.get("maxmemory", 0) or 0)
        ctx["redis"] = {
            "used": info.get("used_memory_human", "?"),
            "max": (f"{round(mx / 1048576)} MB" if mx else "∞"),
            "hit_pct": round(100 * hits / (hits + misses), 1) if (hits + misses) else 0,
            "keys": db0.get("keys", 0) if isinstance(db0, dict) else 0,
        }
    except Exception:
        pass

    # ── Tenants ──
    try:
        from tenants.models import Tenant, Domain
        ctx["tenant_count"] = Tenant.objects.exclude(schema_name="public").count()
        ctx["domain_count"] = Domain.objects.count()
    except Exception:
        pass

    # ── Next import ──
    try:
        r = subprocess.run(["systemctl", "list-timers", "tenant-import.timer", "--no-pager"],
                           capture_output=True, text=True, timeout=3)
        for line in r.stdout.splitlines():
            if "tenant-import" in line:
                ctx["next_import"] = " ".join(line.split()[:3])
                break
    except Exception:
        pass

    return render(request, "vps_health.html", ctx)
