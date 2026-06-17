"""PLUR RFP Tracker - FastAPI + htmx dashboard."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import DATA_DIR
from lib.renewals import RenewalCalendar
from lib.tender_renewals import TenderRenewalCalendar

DB_PATH = DATA_DIR / "rfp.db"
TEMPLATES_DIR = Path(__file__).parent / "templates"

app = FastAPI(title="PLUR RFP Tracker")

# Cache renewal calendar (582MB CSV, load once at startup)
_renewal_cal = None

# Cache tender calendar (small JSON, loads instantly)
_tender_cal = None


def get_renewal_calendar() -> RenewalCalendar:
    global _renewal_cal
    if _renewal_cal is None:
        _renewal_cal = RenewalCalendar(DATA_DIR)
        _renewal_cal.load_data()
    return _renewal_cal


def get_tender_calendar() -> TenderRenewalCalendar:
    global _tender_cal
    if _tender_cal is None:
        _tender_cal = TenderRenewalCalendar(DATA_DIR)
        _tender_cal.load_data()
    return _tender_cal
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def get_db() -> sqlite3.Connection:
    """Read-only SQLite connection."""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Template filters
# ---------------------------------------------------------------------------

def _parse_iso(dt_str: str | None) -> datetime | None:
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str)
    except (ValueError, TypeError):
        return None


def timeago(dt_str: str | None) -> str:
    """Human-readable time-ago string."""
    dt = _parse_iso(dt_str)
    if not dt:
        return "unknown"
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = now - dt
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "just now"
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


def format_date(dt_str: str | None) -> str:
    """Format closing date for display."""
    dt = _parse_iso(dt_str)
    if not dt:
        return "-"
    return dt.strftime("%b %d, %Y")


def days_until(dt_str: str | None) -> int | None:
    """Days until a closing date. Negative = past."""
    dt = _parse_iso(dt_str)
    if not dt:
        return None
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt - now).days


def truncate(text: str, length: int = 80) -> str:
    if len(text) <= length:
        return text
    return text[:length].rstrip() + "..."


def parse_json_safe(text: str, default=None):
    try:
        return json.loads(text) if text else default
    except (json.JSONDecodeError, TypeError):
        return default


def duration_since(end_str: str | None, start_str: str | None) -> str:
    """Human-readable duration between two ISO timestamps."""
    start = _parse_iso(start_str)
    end = _parse_iso(end_str)
    if not start or not end:
        return "-"
    delta = end - start
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "-"
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    secs = seconds % 60
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h {mins}m"


def format_currency(value: float | int | None) -> str:
    """Format a number as currency (e.g. $1,234,567)."""
    if value is None:
        return "-"
    if value >= 1_000_000:
        return f"${value / 1_000_000:,.1f}M"
    if value >= 1_000:
        return f"${value:,.0f}"
    return f"${value:,.2f}"


def is_new(dt_str: str | None, hours: int = 48) -> bool:
    """True if timestamp is within the last N hours."""
    dt = _parse_iso(dt_str)
    if not dt:
        return False
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now - dt).total_seconds() < hours * 3600


templates.env.filters["timeago"] = timeago
templates.env.filters["format_date"] = format_date
templates.env.filters["days_until"] = days_until
templates.env.filters["truncate"] = truncate
templates.env.filters["parse_json"] = parse_json_safe
templates.env.filters["duration_since"] = duration_since
templates.env.filters["format_currency"] = format_currency
templates.env.filters["is_new"] = is_new


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SORT_OPTIONS = {
    "newest": ("fetch_timestamp", "DESC"),
    "oldest": ("fetch_timestamp", "ASC"),
    "closing_soon": ("closing_date", "ASC"),
    "closing_last": ("closing_date", "DESC"),
    "tier": ("json_extract(classification_json, '$.tier')", "ASC"),
    "buyer": ("buyer", "ASC"),
    "title": ("title", "ASC"),
}


def _build_opportunities_query(
    tier: list[int] | None = None,
    source: str | None = None,
    q: str | None = None,
    sort: str = "newest",
) -> tuple[str, list, str]:
    """Build SQL WHERE clause + ORDER BY for opportunities filtering."""
    conditions = []
    params = []

    if tier:
        placeholders = ",".join("?" for _ in tier)
        conditions.append(
            f"json_extract(classification_json, '$.tier') IN ({placeholders})"
        )
        params.extend(tier)

    if source:
        conditions.append("source = ?")
        params.append(source)

    if q:
        conditions.append("(title LIKE ? OR description LIKE ? OR buyer LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like])

    where = " AND ".join(conditions) if conditions else "1=1"
    col, direction = SORT_OPTIONS.get(sort, SORT_OPTIONS["newest"])
    # Put NULLs last for closing_date sorts
    if "closing" in sort:
        order_by = f"CASE WHEN {col} IS NULL OR {col} = '' THEN 1 ELSE 0 END, {col} {direction}"
    else:
        order_by = f"{col} {direction}"
    return where, params, order_by


def _get_stats(conn: sqlite3.Connection) -> dict:
    """Summary statistics."""
    row = conn.execute(
        """
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN json_extract(classification_json, '$.tier') = 1 THEN 1 ELSE 0 END) as t1,
            SUM(CASE WHEN json_extract(classification_json, '$.tier') = 2 THEN 1 ELSE 0 END) as t2,
            SUM(CASE WHEN json_extract(classification_json, '$.tier') = 3 THEN 1 ELSE 0 END) as t3
        FROM notices
        """
    ).fetchone()

    last_run = conn.execute(
        "SELECT MAX(end_time) FROM source_runs WHERE status = 'success'"
    ).fetchone()

    cutoff = (datetime.now(timezone.utc).timestamp() - 48 * 3600)
    new_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM notices WHERE fetch_timestamp >= ?",
        (datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat(),),
    ).fetchone()["cnt"]

    return {
        "total": row["total"],
        "t1": row["t1"],
        "t2": row["t2"],
        "t3": row["t3"],
        "new_48h": new_count,
        "last_scrape": last_run[0] if last_run else None,
    }


def _get_sources(conn: sqlite3.Connection) -> list[str]:
    """Distinct sources."""
    rows = conn.execute("SELECT DISTINCT source FROM notices ORDER BY source").fetchall()
    return [r["source"] for r in rows]


# ---------------------------------------------------------------------------
# HTML routes
# ---------------------------------------------------------------------------

def _list_opportunities(
    request: Request,
    tier: list[int],
    source: str,
    q: str,
    sort: str,
    page: int,
    closed: bool = False,
) -> HTMLResponse:
    """Shared handler for open and closed opportunity listing pages."""
    conn = get_db()
    try:
        where, params, order_by = _build_opportunities_query(
            tier=tier or None,
            source=source or None,
            q=q or None,
            sort=sort,
        )

        if closed:
            where += " AND closing_date IS NOT NULL AND closing_date != '' AND closing_date < ?"
            params.append(datetime.now(timezone.utc).isoformat())
        else:
            where += " AND (closing_date IS NULL OR closing_date = '' OR closing_date >= ?)"
            params.append(datetime.now(timezone.utc).strftime("%Y-%m-%d"))

        count_row = conn.execute(
            f"SELECT COUNT(*) as cnt FROM notices WHERE {where}", params
        ).fetchone()
        total = count_row["cnt"]

        per_page = 25
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = min(page, total_pages)
        offset = (page - 1) * per_page

        rows = conn.execute(
            f"SELECT * FROM notices WHERE {where} ORDER BY {order_by} LIMIT ? OFFSET ?",
            params + [per_page, offset],
        ).fetchall()

        stats = _get_stats(conn)
        sources = _get_sources(conn)

        ctx = {
            "request": request,
            "notices": rows,
            "stats": stats,
            "sources": sources,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "per_page": per_page,
            "filter_tier": tier,
            "filter_source": source,
            "filter_q": q,
            "filter_sort": sort,
            "sort_options": SORT_OPTIONS,
            "active_page": "closed" if closed else "opportunities",
        }

        if request.headers.get("HX-Request"):
            return templates.TemplateResponse(request, "partials/opportunities_table.html", ctx)

        return templates.TemplateResponse(request, "index.html", ctx)
    finally:
        conn.close()


@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    tier: list[int] = Query(default=[]),
    source: str = Query(default=""),
    q: str = Query(default=""),
    sort: str = Query(default="newest"),
    page: int = Query(default=1, ge=1),
):
    return _list_opportunities(request, tier, source, q, sort, page, closed=False)


@app.get("/opportunity/{notice_id}", response_class=HTMLResponse)
async def opportunity_detail(request: Request, notice_id: int):
    """Detail page for a single opportunity."""
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM notices WHERE id = ?", (notice_id,)).fetchone()
        if not row:
            return HTMLResponse("<h1>Not found</h1>", status_code=404)

        classification = parse_json_safe(row["classification_json"], {})
        enrichment = parse_json_safe(row["enrichment_json"], {}) if row["enrichment_json"] else {}
        vendor_flags = parse_json_safe(row["vendor_flags"], [])
        enrichment.setdefault("similar_awards", [])
        enrichment.setdefault("competitive_landscape", {})

        # Build source URL
        source = row["source"] or ""
        if row["url"]:
            source_url = row["url"]
        elif source == "canadabuys" and row["source_id"]:
            source_url = f"https://canadabuys.canada.ca/en/tender-opportunities/tender-notice/{row['source_id']}"
        elif source.startswith("bonfire") and row["source_id"]:
            portal = source.split(":")[1] if ":" in source else ""
            source_url = f"https://{portal}.bonfirehub.ca/opportunities/{row['source_id']}"
        else:
            source_url = ""

        ctx = {
            "request": request,
            "notice": row,
            "classification": classification,
            "enrichment": enrichment,
            "vendor_flags": vendor_flags,
            "source_url": source_url,
            "active_page": "",
        }
        return templates.TemplateResponse(request, "detail.html", ctx)
    finally:
        conn.close()


@app.get("/closed", response_class=HTMLResponse)
async def closed_page(
    request: Request,
    tier: list[int] = Query(default=[]),
    source: str = Query(default=""),
    q: str = Query(default=""),
    sort: str = Query(default="closing_last"),
    page: int = Query(default=1, ge=1),
):
    """Show opportunities with closing dates in the past."""
    return _list_opportunities(request, tier, source, q, sort, page, closed=True)


@app.get("/renewals", response_class=HTMLResponse)
async def renewals_page(
    request: Request,
    vendor: str = Query(default=""),
    dept: str = Query(default=""),
    relevance: str = Query(default=""),
    days: int = Query(default=365, ge=30, le=1825),
    sort: str = Query(default="engage_by"),
    q: str = Query(default=""),
    page: int = Query(default=1, ge=1),
):
    """Software renewal calendar page."""
    cal = get_renewal_calendar()

    all_renewals = cal.get_upcoming_renewals(days_ahead=days)

    # Build dropdown lists from unfiltered results (before filtering)
    departments = sorted(set(
        r["department"] for r in all_renewals
        if len(r["department"]) > 5 and "," not in r["department"][:20]
    ))
    vendors = sorted(set(r["vendor"] for r in all_renewals))

    renewals = list(all_renewals)

    # Apply filters
    if vendor:
        vendor_lower = vendor.lower()
        renewals = [r for r in renewals if vendor_lower in r["vendor"].lower()]
    if dept:
        dept_lower = dept.lower()
        renewals = [r for r in renewals if dept_lower in r["department"].lower()]
    if relevance:
        renewals = [r for r in renewals if r["plur_relevance"] == relevance.upper()]
    if q:
        # Support OR queries: "splunk OR siem" matches either term
        terms = [t.strip().lower() for t in q.split(" OR ") if t.strip()]
        if not terms:
            terms = [q.lower()]

        def _renewal_matches(r: dict, search_terms: list[str]) -> bool:
            haystack = " ".join([
                r["vendor"].lower(),
                r["department"].lower(),
                r["description"].lower(),
                r.get("product", "").lower(),
            ])
            return any(t in haystack for t in search_terms)

        renewals = [r for r in renewals if _renewal_matches(r, terms)]

    # Sort
    sort_keys = {
        "engage_by": ("engage_by", False),
        "engage_by_desc": ("engage_by", True),
        "vendor": ("vendor", False),
        "vendor_desc": ("vendor", True),
        "department": ("department", False),
        "department_desc": ("department", True),
        "value": ("last_contract_value", True),
        "value_asc": ("last_contract_value", False),
        "total_value": ("total_historical_value", True),
        "total_value_asc": ("total_historical_value", False),
        "renewal": ("projected_renewal", False),
        "renewal_desc": ("projected_renewal", True),
        "relevance": ("plur_relevance", False),
        "count": ("purchase_count", True),
    }
    sort_field, sort_reverse = sort_keys.get(sort, sort_keys["engage_by"])
    renewals.sort(key=lambda r: (r.get(sort_field) or ""), reverse=sort_reverse)

    # Compute summary stats (before pagination)
    total_count = len(renewals)
    actionable_count = sum(1 for r in renewals if r["is_actionable"])
    total_value = sum(r["total_historical_value"] for r in renewals)

    # Pagination
    per_page = 50
    total_pages = max(1, (total_count + per_page - 1) // per_page)
    page = min(page, total_pages)
    offset = (page - 1) * per_page
    renewals_page_slice = renewals[offset:offset + per_page]

    # Tender-based renewal intelligence
    tender_cal = get_tender_calendar()
    all_tender_renewals = tender_cal.get_upcoming(days_ahead=days)

    # Apply category/text filter to tender results
    tender_renewals = all_tender_renewals
    if q:
        _cat_map = {
            'dlp': 'dlp', 'data loss': 'dlp', 'forcepoint': 'dlp', 'digital guardian': 'dlp',
            'insider': 'insider_threat', 'varonis': 'insider_threat', 'dtex': 'insider_threat',
            'securonix': 'insider_threat', 'ueba': 'insider_threat',
            'nozomi': 'ot', 'claroty': 'ot', 'dragos': 'ot', 'ot security': 'ot',
            'recorded future': 'cti', 'threat intel': 'cti', 'anomali': 'cti', 'mandiant': 'cti',
            'splunk': 'siem', 'logrhythm': 'siem', 'qradar': 'siem', 'elastic': 'siem',
            'tenable': 'vuln', 'qualys': 'vuln', 'rapid7': 'vuln', 'vulnerability': 'vuln',
            'proofpoint': 'email', 'mimecast': 'email', 'email security': 'email',
            'firewall': 'firewall', 'fortinet': 'firewall', 'palo alto': 'firewall',
            'cyberark': 'iam', 'beyondtrust': 'iam', 'sailpoint': 'iam', 'entrust': 'iam',
            'crowdstrike': 'edr', 'sentinelone': 'edr', 'endpoint': 'edr', 'carbon black': 'edr',
        }
        q_lower = q.lower()
        matched_cat = next((cat for term, cat in _cat_map.items() if term in q_lower), None)
        if matched_cat:
            tender_renewals = [r for r in tender_renewals if r['product_category'] == matched_cat]
        else:
            terms = [t.strip().lower() for t in q.split(' OR ') if t.strip()]
            tender_renewals = [r for r in tender_renewals if any(
                t in r['department'].lower() or t in r['tender_title'].lower() or t in r['search_term'].lower()
                for t in terms
            )]

    # Apply dept filter to tender results too
    if dept:
        dept_lower = dept.lower()
        tender_renewals = [r for r in tender_renewals if dept_lower in r['department'].lower()]

    ctx = {
        "request": request,
        "renewals": renewals_page_slice,
        "total_count": total_count,
        "actionable_count": actionable_count,
        "total_value": total_value,
        "departments": departments,
        "vendors_list": vendors,
        "filter_vendor": vendor,
        "filter_dept": dept,
        "filter_relevance": relevance,
        "filter_days": days,
        "filter_sort": sort,
        "filter_q": q,
        "page": page,
        "total_pages": total_pages,
        "per_page": per_page,
        "active_page": "renewals",
        "tender_renewals": tender_renewals,
        "tender_total": len(tender_renewals),
    }
    return templates.TemplateResponse(request, "renewals.html", ctx)


@app.get("/health", response_class=HTMLResponse)
async def health_page(request: Request):
    conn = get_db()
    try:
        runs = conn.execute(
            """
            SELECT * FROM source_runs
            ORDER BY start_time DESC
            LIMIT 100
            """
        ).fetchall()

        # Summary
        total_sources = conn.execute(
            "SELECT COUNT(DISTINCT source) as cnt FROM source_runs"
        ).fetchone()["cnt"]

        last_full = conn.execute(
            "SELECT MAX(end_time) as t FROM source_runs WHERE status = 'success'"
        ).fetchone()["t"]

        error_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM source_runs WHERE status = 'error'"
        ).fetchone()["cnt"]

        ctx = {
            "request": request,
            "runs": runs,
            "total_sources": total_sources,
            "last_full": last_full,
            "error_count": error_count,
        }
        return templates.TemplateResponse(request, "health.html", ctx)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.get("/api/opportunities")
async def api_opportunities(
    tier: list[int] = Query(default=[]),
    source: str = Query(default=""),
    q: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=100),
):
    conn = get_db()
    try:
        where, params, _ = _build_opportunities_query(
            tier=tier or None,
            source=source or None,
            q=q or None,
        )

        count_row = conn.execute(
            f"SELECT COUNT(*) as cnt FROM notices WHERE {where}", params
        ).fetchone()
        total = count_row["cnt"]

        total_pages = max(1, (total + per_page - 1) // per_page)
        page = min(page, total_pages)
        offset = (page - 1) * per_page

        rows = conn.execute(
            f"""
            SELECT id, source, source_id, title, buyer, closing_date, url,
                   notice_type, product_type, vendor_flags, classification_json,
                   solicitation_number, fetch_timestamp
            FROM notices
            WHERE {where}
            ORDER BY fetch_timestamp DESC
            LIMIT ? OFFSET ?
            """,
            params + [per_page, offset],
        ).fetchall()

        items = []
        for r in rows:
            cls = parse_json_safe(r["classification_json"], {})
            items.append({
                "id": r["id"],
                "source": r["source"],
                "source_id": r["source_id"],
                "title": r["title"],
                "buyer": r["buyer"],
                "closing_date": r["closing_date"],
                "url": r["url"],
                "notice_type": r["notice_type"],
                "product_type": r["product_type"],
                "vendor_flags": parse_json_safe(r["vendor_flags"], []),
                "tier": cls.get("tier"),
                "confidence": cls.get("confidence"),
                "matched_keywords": cls.get("matched_keywords", []),
                "solicitation_number": r["solicitation_number"],
                "fetch_timestamp": r["fetch_timestamp"],
            })

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "items": items,
        }
    finally:
        conn.close()


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Modern demo dashboard."""
    with open(TEMPLATES_DIR / "dashboard.html") as f:
        return f.read()


@app.get("/search", response_class=HTMLResponse)
async def search_page():
    """Search page."""
    with open(TEMPLATES_DIR / "search.html") as f:
        return f.read()


@app.get("/api/health")
async def api_health():
    conn = get_db()
    try:
        runs = conn.execute(
            "SELECT * FROM source_runs ORDER BY start_time DESC LIMIT 50"
        ).fetchall()
        return {
            "status": "healthy",
            "runs": [dict(r) for r in runs],
        }
    finally:
        conn.close()


@app.get("/api/stats")
async def api_stats():
    conn = get_db()
    try:
        stats = _get_stats(conn)
        return stats
    finally:
        conn.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8081)
