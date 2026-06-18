# Example API Response Format

## What Your Backend Needs to Return

The frontend expects the backend to have an endpoint that returns RFP data.

### Endpoint
```
GET /api/rfps
```

### Expected Response Format

```json
[
  {
    "title": "Federal IT Infrastructure Modernization RFP",
    "organization": "Department of Defense",
    "status": "active",
    "deadline": "2026-08-15",
    "value": "$50,000,000",
    "description": "Seeking qualified contractors for comprehensive IT infrastructure modernization including cloud migration, cybersecurity enhancements, and legacy system replacement.",
    "url": "https://www.fbo.gov/..."
  },
  {
    "title": "Healthcare Data Analytics Platform",
    "organization": "Centers for Medicare & Medicaid Services",
    "status": "active",
    "deadline": "2026-07-30",
    "value": "$15,000,000",
    "description": "Request for proposals to develop and implement an advanced data analytics platform for healthcare cost and quality measurement.",
    "url": "https://www.fbo.gov/..."
  },
  {
    "title": "Cybersecurity Framework Implementation",
    "organization": "National Institute of Standards and Technology",
    "status": "upcoming",
    "deadline": "2026-09-15",
    "value": "$5,000,000",
    "description": "RFP for implementation of updated NIST cybersecurity framework across federal agencies.",
    "url": "https://www.fbo.gov/..."
  },
  {
    "title": "Legacy System Migration Project",
    "organization": "Social Security Administration",
    "status": "closed",
    "deadline": "2026-06-30",
    "value": "$25,000,000",
    "description": "Closed RFP for migration of legacy mainframe systems to modern cloud infrastructure. Winner announced.",
    "url": "https://www.fbo.gov/..."
  }
]
```

## Field Definitions

| Field | Type | Required | Example | Notes |
|-------|------|----------|---------|-------|
| title | string | Yes | "Federal IT Infrastructure..." | RFP title, max 200 chars |
| organization | string | Yes | "Department of Defense" | Issuing organization |
| status | string | Yes | "active" | Must be: active, upcoming, or closed |
| deadline | string | Yes | "2026-08-15" | ISO format (YYYY-MM-DD) |
| value | string | Yes | "$50,000,000" | Budget/value estimate |
| description | string | Yes | "Seeking qualified..." | Brief description, max 500 chars |
| url | string | Yes | "https://..." | Link to full RFP |

## Status Values

```
"active"    - Currently open, accepting proposals
"upcoming"  - Will be released soon
"closed"    - No longer accepting proposals
```

## Frontend Features Based on Data

### Status Badges
- **Active** (green): `"status": "active"`
- **Upcoming** (orange): `"status": "upcoming"`
- **Closed** (gray): `"status": "closed"`

### Stats Dashboard
- **Total RFPs**: Count all items
- **Active**: Count where `status === "active"`
- **Upcoming**: Count where `status === "upcoming"`
- **Closed**: Count where `status === "closed"`

### Search Filters
- Searches `title` and `organization` (case-insensitive)
- Filters by `status` dropdown
- Shows total matching RFPs

### Card Display
- Title (truncated if too long)
- Status badge (color-coded)
- Organization name
- Deadline date
- Value estimate
- Description preview (first 150 chars + "...")
- "View Full RFP" link

## Minimal Example (for testing)

If you want to test the frontend quickly with dummy data, add this endpoint:

```python
@app.get("/api/rfps")
def get_rfps():
    return [
        {
            "title": "Test RFP 1",
            "organization": "Test Org",
            "status": "active",
            "deadline": "2026-12-31",
            "value": "$100,000",
            "description": "This is a test RFP",
            "url": "https://example.com"
        }
    ]
```

The frontend will immediately show this data.

## Health Check Endpoint (Optional)

Also recommended to add:

```python
@app.get("/api/health")
def health_check():
    return {"status": "ok"}
```

The frontend uses this to verify backend connectivity.

## Testing Your API

```bash
# Check if endpoint exists and returns proper format
curl http://52.207.113.238/api/rfps | jq .

# Should output JSON array like the example above
```

## CORS Headers Required

Your backend must include CORS headers:

```python
# If using FastAPI
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Without these, the frontend will get blocked by browser security.

## Common Issues

### Frontend Shows "Failed to load RFPs"

1. **CORS error**: Backend missing CORS headers
2. **Endpoint missing**: `/api/rfps` doesn't exist
3. **Wrong format**: Response isn't a valid JSON array
4. **Backend down**: Server not running

### Stats Show 0 RFPs

- Check endpoint returns array: `curl http://52.207.113.238/api/rfps`
- Should be `[{...}, {...}]` not `{...}`
- Check status field is "active", "upcoming", or "closed"

### Data Not Updating

- Refresh button in frontend sends GET request each time
- Frontend fetches data on page load
- For real-time updates, add cache headers to your API

## Performance Tips

1. **Pagination** (optional): Add limit/offset parameters if you have many RFPs
2. **Caching**: Add `Cache-Control` headers to reduce repeated requests
3. **Compression**: Enable gzip compression for faster response
4. **Database indexing**: Index `status` field for faster filtering

---

**Example Dashboard URL**: https://aronhsiao-pl.github.io/plur-rfp-tracker-v2

Just ensure your `/api/rfps` endpoint returns data in this format and the dashboard will work perfectly!
