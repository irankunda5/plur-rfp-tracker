# RFP Tracker Current State / Handoff

## Summary

The RFP Tracker is a procurement opportunity monitoring system for finding relevant public-sector RFP/RFQ/RFI opportunities, classifying them for Plurilock relevance, storing them in SQLite, and syncing actionable records into HubSpot as Signals.

The current codebase has been moved toward a v2 config-driven architecture. Instead of requiring custom scraper code for every source, v2 allows sources to be defined through YAML configuration files where possible. These configs describe the source URL, source type, field mappings, validation rules, health expectations, and production/testing status. The shared pipeline then handles extraction, validation, classification, storage, and HubSpot sync.

The core implementation is locally verified and ready for deployment attempt, but production deployment is currently blocked by EC2/access permissions. The current state should therefore be understood as:

```text
Implementation state: locally verified and deployment-prepared
Deployment state: blocked by EC2 access and still needs production monitoring
```

---

## Recommended Branch

Use:

```bash
hubspot-signals-integration
```

This branch contains both:

```text
v2 runtime integration
automated HubSpot sync
```

At the time of branch comparison, `main` had HubSpot automation but did not have the completed v2 runtime integration. For v2 deployment/testing, `hubspot-signals-integration` is the recommended branch.

---

## Current Architecture

The v2 pipeline is:

```text
Source YAML config
→ extractor
→ RawOpportunity
→ validator
→ classifier
→ SQLite storage
→ HubSpot Signals sync
```

The key platform contract is `RawOpportunity`. All source types should normalize their records into this shape before downstream processing.

Conceptually:

```text
CSV / JSON / HTML source
→ normalized opportunity record
→ common validation/classification/storage/output flow
```

This keeps downstream logic independent of source-specific formats.

---

## What Works Locally

The following pieces are currently implemented and working locally:

```text
v2 config discovery
V2_MODE production source discovery
V2_SOURCES explicit source selection
CSV extraction
JSON API extraction
RawOpportunity normalization
record validation
confidence scoring
keyword classification
SQLite storage
deduplication
source run tracking
HubSpot migration
manual HubSpot sync
automated HubSpot sync after scraper runs
```

The codebase remains backward compatible with v1 scrapers while sources are gradually migrated into v2.

---

## Source Coverage

### Production v2 Sources

These are the currently validated v2 sources:

| Source           | Type     | Status     | Notes                              |
| ---------------- | -------- | ---------- | ---------------------------------- |
| `canadabuys_csv` | CSV      | Production | Validated locally, high confidence |
| `bonfire_json`   | JSON API | Production | Validated locally, high confidence |

These are the only sources that should be included in the current production/deployment snapshot.

### Testing / Blocked Sources

| Source              | Type                | Status               | Blocker                                                            |
| ------------------- | ------------------- | -------------------- | ------------------------------------------------------------------ |
| `sam_gov_json`      | JSON API            | Testing              | Requires `SAM_GOV_API_KEY`                                         |
| `sasktenders_html`  | HTML                | Testing              | Requires JavaScript rendering support                              |
| `canadabuys_search` | HTML/search crawler | Testing / incomplete | Requires search crawler architecture with pagination/deduplication |

---

## Runtime Modes

### Run explicit v2 sources

```bash
V2_SOURCES=canadabuys_csv,bonfire_json python3 run.py --once
```

### Run all production v2 sources

```bash
V2_MODE=true python3 run.py --once
```

### Run a single v2 source

```bash
V2_SOURCES=canadabuys_csv python3 run.py --scraper canadabuys_csv
```

### Run legacy v1 mode

```bash
python3 run.py --once
```

If no v2 flags are set, the system can still fall back to legacy v1 behavior.

---

## HubSpot Integration

HubSpot sync is implemented as a decoupled output layer. After scraping completes, `run.py` checks whether HubSpot environment variables are present. If they are, it automatically runs the HubSpot sync process.

Required environment variables:

```bash
export HUBSPOT_API_KEY="<private app token>"
export HUBSPOT_OBJECT_TYPE_ID="2-229341360"
```

Important: do not commit the actual HubSpot token to the repository or write it into documentation. Store it only in the deployment environment or a secrets manager.

### HubSpot Sync Behavior

HubSpot sync is:

```text
automatic after scraper execution
gated by environment variables
batch-based
idempotent
tracked in SQLite
isolated from scraper failures
```

If HubSpot sync fails, scraping should still be treated as successful. HubSpot errors are logged, but they do not change the original scraper exit code.

### HubSpot Migration

Run once before syncing:

```bash
python3 scripts/migrate_hubspot_columns.py
```

The migration is idempotent and adds HubSpot tracking columns to the `notices` table:

```text
hubspot_synced
hubspot_id
hubspot_sync_at
hubspot_sync_error
```

### Manual HubSpot Sync

```bash
python3 scripts/sync_hubspot.py --batch-size 5
```

Dry-run if supported:

```bash
python3 scripts/sync_hubspot.py --batch-size 5 --dry-run
```

---

## Validation Status

The two production v2 sources were tested through an accelerated local validation process.

Results from executed runs:

```text
canadabuys_csv: successful local runs, high confidence
bonfire_json: successful local runs, high confidence
0 observed duplicate records
0 observed scraper crashes
0 observed extraction failures in executed runs
```

Important caveat:

The local 72-hour validation did not complete every expected cron window because the local macOS development machine went to sleep. This caused scheduled jobs to be missed. The missed runs were an environment limitation, not an observed scraper failure.

Conclusion:

```text
The code paths worked reliably when executed locally.
Always-on EC2 deployment is still required to validate uninterrupted 24/7 behavior.
```

Recommended post-deployment validation:

```text
Deploy only canadabuys_csv and bonfire_json
Monitor every scheduled run for the first 24–48 hours
Confirm scraper success rate, confidence scores, duplicates, and HubSpot sync health
```

---

## Deployment Status

The deployment procedure is documented, but deployment is currently blocked by EC2/access permissions.

I do not currently have the EC2 access needed to:

```text
pull the deployment branch onto the production server
set server-side environment variables
run the HubSpot migration on EC2
configure cron
monitor production logs directly
verify production HubSpot sync
```

Once EC2 access is available, the recommended initial deployment flow is:

```bash
git checkout hubspot-signals-integration
git pull origin hubspot-signals-integration

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

export V2_MODE=true
export HUBSPOT_API_KEY="<private app token>"
export HUBSPOT_OBJECT_TYPE_ID="2-229341360"

python3 scripts/migrate_hubspot_columns.py
V2_MODE=true python3 run.py --once
```

Recommended cron mode:

```bash
0 */6 * * * cd /opt/rfp-tracker && V2_MODE=true python3 run.py --once >> logs/v2_scrapers.log 2>&1
```

For more explicit source control, use:

```bash
V2_SOURCES=canadabuys_csv,bonfire_json
```

instead of `V2_MODE=true`.

---

## Known Gaps / Recommended Fixes

### 1. EC2 Deployment Access

Deployment cannot be completed until EC2 access/permissions are resolved.

This is the main operational blocker.

### 2. Deadline Filtering for HubSpot

Expired RFPs should not appear as active HubSpot Signals.

Recommended behavior:

```text
keep expired opportunities in SQLite for history/deduplication
skip expired opportunities during active HubSpot sync
optionally allow a configurable grace period
```

Suggested first implementation target:

```text
filter HubSpot sync query by closing_date / deadline
log skipped expired records
preserve internal storage behavior
```

### 3. Local Verification Script

Because deployment access is blocked, the repo should include a local verification command that proves the pipeline works without EC2.

Suggested command:

```bash
python3 scripts/verify_pipeline.py
```

Suggested checks:

```text
config loading
source extraction
validation
confidence scoring
database write/dedupe
HubSpot dry-run or sync check
deadline filtering
run tracking
```

This would replace vague “production readiness” language with a concrete local verification milestone.

### 4. Confidence Gates

Confidence scoring exists, but it should be used more actively for operational decisions.

Recommended behavior:

```text
confidence >= 0.90: auto-approve
0.60 <= confidence < 0.90: store but flag for review
confidence < 0.60: block downstream sync and escalate
```

### 5. Structured Breakage Reports

Before true self-healing is possible, failures need to be categorized and explained.

Example report:

```text
Source: sasktenders_html
Status: failed
Category: JavaScript rendering / extraction failure
Current confidence: 0.28
Likely cause: source changed rendering behavior
Suggested fix: test Playwright-based extractor
```

### 6. Claude-Assisted Config Repair

Longer term, Claude/API calls should be used selectively for source-level repair, not for every record.

Recommended use cases:

```text
new source config generation
field mapping suggestions
selector repair
schema drift diagnosis
low-confidence run explanation
config diff generation
```

Claude should not be in the hot path for every scraped opportunity. It should be used when a source breaks, when confidence drops, or when a new source is being onboarded.

---

## Remaining Source Work

### SAM.gov

Status:

```text
blocked on SAM_GOV_API_KEY
```

Next step:

```bash
export SAM_GOV_API_KEY="<key>"
V2_SOURCES=sam_gov_json python3 run.py --scraper sam_gov_json
```

If validation succeeds, this is likely the easiest third production source because the JSON API pattern already exists.

### SaskTenders

Status:

```text
blocked by JavaScript-rendered source behavior
```

Next step:

```text
decide whether to add Playwright/Selenium support
or replace source strategy if a structured feed/API is available
```

### CanadaBuys Search

Status:

```text
requires search crawler architecture
```

Likely requirements:

```text
multiple URLs
pagination
search-term iteration
open/closed tender handling
cross-page deduplication
source-specific result normalization
```

This is larger than a single YAML config.

---

## Operations / Monitoring

Useful database checks:

### Recent runs

```bash
sqlite3 data/rfp.db "
SELECT source, start_time, status, records_found, records_new
FROM source_runs
ORDER BY id DESC
LIMIT 10;
"
```

### HubSpot sync status

```bash
sqlite3 data/rfp.db "
SELECT
    COUNT(*) as total,
    SUM(hubspot_synced) as synced,
    SUM(CASE WHEN hubspot_synced = 0 THEN 1 ELSE 0 END) as pending
FROM notices;
"
```

### Duplicates

```bash
sqlite3 data/rfp.db "
SELECT source, source_id, COUNT(*)
FROM notices
GROUP BY source, source_id
HAVING COUNT(*) > 1;
"
```

### Failed HubSpot syncs

```bash
sqlite3 data/rfp.db "
SELECT id, source, title, hubspot_sync_error
FROM notices
WHERE hubspot_sync_error IS NOT NULL
ORDER BY hubspot_sync_at DESC
LIMIT 10;
"
```

---

## Security Notes

Do not commit:

```text
HubSpot private app token
AWS credentials
SAM.gov API key
Slack webhook URLs
.env files
local database files with sensitive sync metadata
```

Documentation should refer to secrets as placeholders:

```bash
HUBSPOT_API_KEY="<private app token>"
SAM_GOV_API_KEY="<key>"
```

not real values.

---

## Recommended Next Development Order

Given that EC2 deployment is blocked by access, the recommended development path is:

```text
1. Finalize repo documentation and handoff notes
2. Add deadline filtering to HubSpot sync
3. Add local verification script
4. Add confidence-based health gates
5. Add structured breakage reports
6. Add Claude-assisted config repair prototype
7. Validate SAM.gov once API key is available
8. Design CanadaBuys Search crawler architecture
9. Add JavaScript-rendering strategy for SaskTenders
10. Resolve EC2 access and complete production deployment
```

---

## Final State

The codebase has a working v2 config-driven foundation, two validated production v2 sources, automated HubSpot sync, and documentation for deployment and operations.

The most important distinction is:

```text
Core implementation: mostly complete for the validated v2 snapshot
Production deployment: still blocked by EC2/access and requires live monitoring
```

Once access is resolved, the recommended deployment scope is:

```text
branch: hubspot-signals-integration
sources: canadabuys_csv, bonfire_json
mode: V2_MODE=true or explicit V2_SOURCES
output: HubSpot Signals
monitoring: first 24–48 hours
```

Do not include `sam_gov_json`, `sasktenders_html`, or `canadabuys_search` in production until their blockers are resolved and they pass validation.
