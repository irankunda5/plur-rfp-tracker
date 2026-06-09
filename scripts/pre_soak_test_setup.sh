#!/usr/bin/env bash
# Pre-Soak Test Setup Script
# Validates environment and creates required directories before starting 7-day v2 multi-source soak test

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=========================================="
echo "Pre-Soak Test Setup"
echo "=========================================="
echo ""

# 1. Verify project directory
echo "[1/6] Verifying project directory..."
if [ ! -f "$PROJECT_DIR/run.py" ]; then
    echo "ERROR: run.py not found. Are you in the correct directory?"
    exit 1
fi
echo "  ✓ Project directory: $PROJECT_DIR"
echo ""

# 2. Create required directories
echo "[2/6] Creating required directories..."
mkdir -p "$PROJECT_DIR/data"
mkdir -p "$PROJECT_DIR/data/backups"
mkdir -p "$PROJECT_DIR/logs"
echo "  ✓ data/"
echo "  ✓ data/backups/"
echo "  ✓ logs/"
echo ""

# 3. Verify Python dependencies
echo "[3/6] Verifying Python dependencies..."
cd "$PROJECT_DIR"
if ! python3 -c "import pandas, httpx, pydantic, yaml" 2>/dev/null; then
    echo "  WARNING: Some Python dependencies missing. Install with:"
    echo "    pip install -r requirements.txt"
    echo ""
else
    echo "  ✓ Core dependencies installed"
    echo ""
fi

# 4. Verify v2 configs exist
echo "[4/6] Verifying v2 configs..."
if [ ! -f "$PROJECT_DIR/configs/canadabuys_csv.yaml" ]; then
    echo "  ERROR: configs/canadabuys_csv.yaml not found"
    exit 1
fi
echo "  ✓ configs/canadabuys_csv.yaml exists"

if [ ! -f "$PROJECT_DIR/configs/bonfire_json.yaml" ]; then
    echo "  ERROR: configs/bonfire_json.yaml not found"
    exit 1
fi
echo "  ✓ configs/bonfire_json.yaml exists"
echo ""

# 5. Initialize database (creates schema if needed)
echo "[5/6] Initializing database..."
if [ -f "$PROJECT_DIR/data/rfp.db" ]; then
    echo "  ✓ Database exists: data/rfp.db"

    # Check if HubSpot columns exist
    HUBSPOT_COL_COUNT=$(sqlite3 "$PROJECT_DIR/data/rfp.db" "PRAGMA table_info(notices);" 2>/dev/null | grep "hubspot" | wc -l | tr -d ' ')
    if [ "$HUBSPOT_COL_COUNT" -eq 0 ]; then
        echo "  ⚠ HubSpot columns not found. Run migration:"
        echo "    python3 scripts/migrate_hubspot_columns.py"
        echo ""
    else
        echo "  ✓ HubSpot columns present ($HUBSPOT_COL_COUNT columns)"
        echo ""
    fi
else
    echo "  ℹ Database will be created on first run"
    echo ""
fi

# 6. Test database backup safety
echo "[6/6] Testing database backup..."
if [ -f "$PROJECT_DIR/data/rfp.db" ]; then
    # Test .backup command (safe for WAL mode)
    BACKUP_TEST="$PROJECT_DIR/data/backups/test_$(date +%Y%m%d_%H%M%S).db"
    if sqlite3 "$PROJECT_DIR/data/rfp.db" ".backup '$BACKUP_TEST'" 2>/dev/null; then
        # Verify backup is valid
        if sqlite3 "$BACKUP_TEST" "SELECT COUNT(*) FROM sqlite_master;" >/dev/null 2>&1; then
            echo "  ✓ Backup test successful (using .backup command)"
            rm -f "$BACKUP_TEST"
        else
            echo "  ⚠ Backup created but may be corrupt"
        fi
    else
        echo "  ⚠ Backup failed"
    fi
else
    echo "  ℹ Skipping backup test (no database yet)"
fi
echo ""

# Summary
echo "=========================================="
echo "Setup Complete"
echo "=========================================="
echo ""
echo "Next steps:"
echo "  1. (Optional) Run HubSpot migration if needed:"
echo "     python3 scripts/migrate_hubspot_columns.py"
echo ""
echo "  2. Test v2 runtime manually:"
echo "     V2_SOURCES=canadabuys_csv python3 run.py --scraper canadabuys_csv"
echo "     V2_SOURCES=bonfire_json python3 run.py --scraper bonfire_json"
echo ""
echo "  3. Verify run tracking:"
echo "     sqlite3 data/rfp.db \"SELECT source, status FROM source_runs ORDER BY id DESC LIMIT 2;\""
echo ""
echo "  4. Add to cron (see SOAK_TEST_QUICK_START.md for details)"
echo ""
