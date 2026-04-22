"""HappyCar insurance-auction scraper (library — no CLI).

Used by the `import_happycar` management command. Exposes:

    scrape_list(cookie, max_pages=None) -> list[dict], total
    scrape_details(idxs, cookie, workers=8) -> None (populates cache)
    parse_detail_html(html: str) -> dict
    enrich(rows: list[dict]) -> list[dict]

All HTTP calls go through `urllib.request` (stdlib only). Cached HTML lives
under `BASE_DIR/.happycar_cache/` so reruns can parse without re-fetching.
"""
from __future__ import annotations

import concurrent.futures
import re
import time
import urllib.request
from pathlib import Path
from typing import Iterable

from django.conf import settings

from . import classifier as _classify

BASE_URL = "https://www.happycarservice.com"
LIST_AJAX = f"{BASE_URL}/content/auction_ins.ajax.html"
DETAIL_URL = f"{BASE_URL}/content/ins_view.html"
PAGE_SIZE = 33

CACHE_DIR = Path(settings.BASE_DIR) / ".happycar_cache"
DETAILS_DIR = CACHE_DIR / "details"
for _d in (CACHE_DIR, DETAILS_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def _headers(cookie: str) -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 Chrome/147.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Referer": f"{BASE_URL}/content/auction_ins.html",
        "Cookie": cookie or "",
        "X-Requested-With": "XMLHttpRequest",
    }


def fetch(url: str, cookie: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers=_headers(cookie))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def list_url(page: int) -> str:
    return (
        f"{LIST_AJAX}?code=&mode=list&page={page}&pageSize0={PAGE_SIZE}"
        "&gallerySel=&sOrder=&sOrderArrow=&au_gubun=&search_name_text="
        "&au_gubun_chk=&start_auregModelY=&start_auregModelM="
        "&end_auregModelY=&end_auregModelM=&au_keepArea=&f_gbn=&f_text="
    )


# ---------- list-page parsing ----------
LI_RE = re.compile(r"<li>(.*?)</li>", re.S)
IDX_RE = re.compile(r"ins_view\.html\?idx=(\d+)")
THUMB_RE = re.compile(r"img-wrap'?\s*style=\"background-image:url\('([^']+)'\)")
STATUS_RE = re.compile(r"<label class='status\d'>([^<]+)</label>")
TITLE_RE = re.compile(r"<strong class='title'>([^<]*)</strong>")
SUB_RE = re.compile(r"<span class='subtitle'>([^<]*)</span>")
DESC_RE = re.compile(r"<span class='car-desc'>(.*?)</span>", re.S)
AUC_TIME_RE = re.compile(r"<span>마감시간</span><span[^>]*>([^<]+)</span>")
MIN_PRICE_RE = re.compile(r"<span>최소입찰금액</span><span[^>]*>([^<]+)</span>")
LOC_RE = re.compile(r"<span>보관지역</span><span[^>]*>([^<]+)</span>")
TOTAL_RE = re.compile(r"setTotalCount\((\d+)\)")


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("<em></em>", " / ")).strip()


def _first(rx: re.Pattern[str], html: str) -> str:
    m = rx.search(html)
    return m.group(1).strip() if m else ""


def parse_list_html(html: str) -> list[dict]:
    rows: list[dict] = []
    for m in LI_RE.finditer(html):
        block = m.group(1)
        idx_m = IDX_RE.search(block)
        if not idx_m:
            continue
        idx = idx_m.group(1)
        thumb = _first(THUMB_RE, block)
        rows.append({
            "idx": idx,
            "detail_url": f"{DETAIL_URL}?idx={idx}",
            "status": _first(STATUS_RE, block),
            "title": _first(TITLE_RE, block),
            "subtitle": _first(SUB_RE, block),
            "desc": _clean(_first(DESC_RE, block)),
            "auction_time": _first(AUC_TIME_RE, block),
            "min_price": _first(MIN_PRICE_RE, block),
            "location": _first(LOC_RE, block),
            "thumbnail": BASE_URL + thumb if thumb else "",
        })
    return rows


# ---------- detail parsing ----------
H2_RE = re.compile(r'<div class="head">\s*<h2>([^<]*)', re.S)
DESC_FULL_RE = re.compile(r'<p class="car-desc">([^<]+)</p>')
KV_RE = re.compile(r"<li><span>([^<]+)</span><span[^>]*>([^<]+)</span></li>")
IMG_RE = re.compile(
    r"(/nBoard/upload/file/\d+/(?!thumbnail)[^'\"\s)>]+\.(?:jpg|jpeg|png|gif|webp))", re.I
)
REG_RE = re.compile(r"copyText\('([^']+)'\);")
MINPRICE_HIDDEN_RE = re.compile(r'id="au_minPrice_chk" value="(\d+)"')
DETAIL01_RE = re.compile(r'<div class="detail-info01">\s*<ul>(.*?)</ul>', re.S)
DETAIL01_LI_RE = re.compile(r"<li>([^<]+?)<p>([^<]+)</p></li>")
DETAIL02_RE = re.compile(r'<div class="detail-info02">\s*<ul>(.*?)</ul>', re.S)
DETAIL02_LI_RE = re.compile(
    r'<li>\s*<p class="count">([^<]*)</p>\s*'
    r'<p class="title">([^<]+?)(?:<span>([^<]*)</span>)?</p>', re.S
)

CARINFO_KEYMAP = {
    "차량설명": "vehicle_desc",
    "보관장소": "storage_location",
    "최소입찰금액": "min_bid_price",
    "경매종료일시": "auction_end",
}
DETAIL01_KEYMAP = {
    "등록연식": "year_month",
    "변속기": "transmission",
    "연료": "fuel",
    "배기량": "displacement",
    "주행거리": "mileage",
    "최소입찰금액": "min_bid_price",
    "보관장소": "storage_location",
    "경매종료일시": "auction_end",
    "발생비용처리": "cost_handling",
}
INSURANCE_KEYMAP = {
    "차량 번호변경": "plate_changes",
    "소유자변경": "owner_changes",
    "내차피해": "own_damage",
    "상대차 피해": "opposing_damage",
}


def _only_digits(s: str) -> int | None:
    d = re.sub(r"[^\d]", "", s or "")
    return int(d) if d else None


def _parse_year_month(s: str) -> tuple[int | None, int | None]:
    m = re.search(r"(\d{4})\s*년\s*(\d{1,2})?\s*월?", s or "")
    if m:
        return int(m.group(1)), int(m.group(2)) if m.group(2) else None
    return None, None


def parse_detail_html(html: str) -> dict:
    out: dict = {}
    if (m := H2_RE.search(html)):
        out["title_full"] = m.group(1).strip()
    if (m := DESC_FULL_RE.search(html)):
        out["desc_full"] = m.group(1).strip()
    if (m := REG_RE.search(html)):
        out["registration_no"] = m.group(1)
    if (m := MINPRICE_HIDDEN_RE.search(html)):
        out["min_bid_price_num"] = int(m.group(1))

    ci = re.search(r'<ul class="carInfo">(.*?)</ul>', html, re.S)
    if ci:
        for k, v in KV_RE.findall(ci.group(1)):
            key = CARINFO_KEYMAP.get(k.strip(), "kv_" + k.strip())
            out.setdefault(key, re.sub(r"\s+", " ", v.strip()))

    if (blk := DETAIL01_RE.search(html)):
        for k, v in DETAIL01_LI_RE.findall(blk.group(1)):
            key = DETAIL01_KEYMAP.get(k.strip(), "kv_" + k.strip())
            out[key] = re.sub(r"\s+", " ", v.strip())

    if (y_m := out.get("year_month")):
        y, mo = _parse_year_month(y_m)
        if y is not None:
            out["year"] = y
        if mo is not None:
            out["month"] = mo
    if (cc := out.get("displacement")) and (n := _only_digits(cc)) is not None:
        out["displacement_cc"] = n
    if (km := out.get("mileage")) and (n := _only_digits(km)) is not None:
        out["mileage_km"] = n

    if (blk := DETAIL02_RE.search(html)):
        ins: dict[str, str] = {}
        for count, title, span in DETAIL02_LI_RE.findall(blk.group(1)):
            t = title.strip()
            key = INSURANCE_KEYMAP.get(t, "ins_" + t)
            val = (count or "").strip()
            if span and span.strip():
                val = f"{val} ({span.strip()})" if val else span.strip()
            ins[key] = val
        if ins:
            out["insurance_history"] = ins

    imgs = sorted(set(IMG_RE.findall(html)))
    out["image_count"] = len(imgs)
    out["images"] = [BASE_URL + i for i in imgs]
    return out


# ---------- orchestration ----------
def scrape_list(
    cookie: str,
    max_pages: int | None = None,
    log=print,
) -> tuple[list[dict], int]:
    """Fetch every list page. Returns (unique rows, total reported by site)."""
    records: dict[str, dict] = {}
    total = 0
    page = 1
    while True:
        if max_pages and page > max_pages:
            break
        html = fetch(list_url(page), cookie).decode("euc-kr", errors="replace")
        if page == 1 and (m := TOTAL_RE.search(html)):
            total = int(m.group(1))
        rows = parse_list_html(html)
        if not rows:
            break
        new = 0
        for r in rows:
            if r["idx"] not in records:
                records[r["idx"]] = r
                new += 1
        log(f"  list page {page}: {len(rows)} rows ({new} new, {len(records)} total)")
        (CACHE_DIR / f"list_{page}.html").write_text(html, encoding="utf-8")
        page += 1
        if new == 0:
            break
        if max_pages is None and total and len(records) >= total:
            break
    return list(records.values()), total


def scrape_details(
    idxs: Iterable[str],
    cookie: str,
    workers: int = 8,
    log=print,
) -> None:
    idxs = list(idxs)

    def one(idx: str) -> tuple[str, int]:
        p = DETAILS_DIR / f"{idx}.html"
        if p.exists() and p.stat().st_size > 5000:
            return idx, p.stat().st_size
        data = fetch(f"{DETAIL_URL}?idx={idx}", cookie)
        p.write_bytes(data)
        return idx, len(data)

    t0 = time.time()
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        for _idx, _size in ex.map(one, idxs):
            done += 1
            if done % 50 == 0 or done == len(idxs):
                log(f"  detail {done}/{len(idxs)}  ({time.time() - t0:.1f}s)")


def enrich(rows: list[dict]) -> list[dict]:
    """Attach detail fields + classifier results to each row."""
    for r in rows:
        p = DETAILS_DIR / f"{r['idx']}.html"
        if p.exists():
            html = p.read_bytes().decode("euc-kr", errors="replace")
            r.update(parse_detail_html(html))
        title_full = r.get("title_full") or r.get("title") or ""
        r.update(_classify.classify(title_full))
    return rows
