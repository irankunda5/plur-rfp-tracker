#!/usr/bin/env bash
# Install Soak Test Cron Entries
# Safe cron installer for v2 multi-source soak test (CanadaBuys + Bonfire)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Default to print-only mode (safe)
APPLY=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --apply)
            APPLY=true
            shift
            ;;
        --print-only)
            APPLY=false
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--print-only|--apply]"
            exit 1
            ;;
    esac
done

echo "=========================================="
echo "Soak Test Cron Installer"
echo "=========================================="
echo ""

# Detect Python path
PYTHON_PATH=$(which python3)
if [ -z "$PYTHON_PATH" ]; then
    echo "ERROR: python3 not found in PATH"
    exit 1
fi
echo "Detected Python: $PYTHON_PATH"
echo "Project Directory: $PROJECT_DIR"
echo ""

# Define cron entries
BACKUP_CRON="0 2 * * * sqlite3 $PROJECT_DIR/data/rfp.db \".backup '$PROJECT_DIR/data/backups/rfp_\$(date +\\%Y\\%m\\%d).db'\""
CLEANUP_CRON="0 3 * * 0 find $PROJECT_DIR/data/backups -name \"rfp_*.db\" -mtime +30 -delete"
SCRAPER_CANADABUYS_CRON="0 */6 * * * cd $PROJECT_DIR && V2_SOURCES=canadabuys_csv $PYTHON_PATH run.py --scraper canadabuys_csv >> logs/canadabuys_csv_cron.log 2>&1"
SCRAPER_BONFIRE_CRON="30 */6 * * * cd $PROJECT_DIR && V2_SOURCES=bonfire_json $PYTHON_PATH run.py --scraper bonfire_json >> logs/bonfire_json_cron.log 2>&1"

# Get current crontab
CURRENT_CRONTAB=$(crontab -l 2>/dev/null || echo "")

# Check for existing entries
BACKUP_EXISTS=$(echo "$CURRENT_CRONTAB" | grep "rfp_tracker.*backup" | wc -l | tr -d ' ')
CLEANUP_EXISTS=$(echo "$CURRENT_CRONTAB" | grep "rfp_tracker.*backups.*mtime" | wc -l | tr -d ' ')
SCRAPER_CANADABUYS_EXISTS=$(echo "$CURRENT_CRONTAB" | grep "V2_SOURCES=canadabuys_csv.*run.py" | wc -l | tr -d ' ')
SCRAPER_BONFIRE_EXISTS=$(echo "$CURRENT_CRONTAB" | grep "V2_SOURCES=bonfire_json.*run.py" | wc -l | tr -d ' ')

# Handle empty results (set to 0 if empty)
[ -z "$BACKUP_EXISTS" ] && BACKUP_EXISTS=0
[ -z "$CLEANUP_EXISTS" ] && CLEANUP_EXISTS=0
[ -z "$SCRAPER_CANADABUYS_EXISTS" ] && SCRAPER_CANADABUYS_EXISTS=0
[ -z "$SCRAPER_BONFIRE_EXISTS" ] && SCRAPER_BONFIRE_EXISTS=0

echo "Current crontab status:"
if [ "$BACKUP_EXISTS" -gt 0 ]; then
    echo "  ✓ Daily backup entry exists"
else
    echo "  ✗ Daily backup entry missing"
fi
if [ "$CLEANUP_EXISTS" -gt 0 ]; then
    echo "  ✓ Weekly cleanup entry exists"
else
    echo "  ✗ Weekly cleanup entry missing"
fi
if [ "$SCRAPER_CANADABUYS_EXISTS" -gt 0 ]; then
    echo "  ✓ V2 canadabuys_csv scraper entry exists"
else
    echo "  ✗ V2 canadabuys_csv scraper entry missing"
fi
if [ "$SCRAPER_BONFIRE_EXISTS" -gt 0 ]; then
    echo "  ✓ V2 bonfire_json scraper entry exists"
else
    echo "  ✗ V2 bonfire_json scraper entry missing"
fi
echo ""

# Build new crontab
NEW_CRONTAB="$CURRENT_CRONTAB"

# Add comment header if first entry
if [ -z "$CURRENT_CRONTAB" ] || ! echo "$CURRENT_CRONTAB" | grep -q "# RFP Tracker v2 Soak Test"; then
    if [ -n "$NEW_CRONTAB" ]; then
        NEW_CRONTAB="$NEW_CRONTAB"$'\n'
    fi
    NEW_CRONTAB="${NEW_CRONTAB}# RFP Tracker v2 Soak Test - Added $(date +%Y-%m-%d)"
fi

# Add backup entry if missing
if [ "$BACKUP_EXISTS" -eq 0 ]; then
    NEW_CRONTAB="$NEW_CRONTAB"$'\n'"$BACKUP_CRON"
fi

# Add cleanup entry if missing
if [ "$CLEANUP_EXISTS" -eq 0 ]; then
    NEW_CRONTAB="$NEW_CRONTAB"$'\n'"$CLEANUP_CRON"
fi

# Add scraper entries if missing
if [ "$SCRAPER_CANADABUYS_EXISTS" -eq 0 ]; then
    NEW_CRONTAB="$NEW_CRONTAB"$'\n'"$SCRAPER_CANADABUYS_CRON"
fi
if [ "$SCRAPER_BONFIRE_EXISTS" -eq 0 ]; then
    NEW_CRONTAB="$NEW_CRONTAB"$'\n'"$SCRAPER_BONFIRE_CRON"
fi

# Show what will be added
if [ "$BACKUP_EXISTS" -eq 0 ] || [ "$CLEANUP_EXISTS" -eq 0 ] || [ "$SCRAPER_CANADABUYS_EXISTS" -eq 0 ] || [ "$SCRAPER_BONFIRE_EXISTS" -eq 0 ]; then
    echo "The following entries will be added:"
    echo "------------------------------------------"
    [ "$BACKUP_EXISTS" -eq 0 ] && echo "$BACKUP_CRON"
    [ "$CLEANUP_EXISTS" -eq 0 ] && echo "$CLEANUP_CRON"
    [ "$SCRAPER_CANADABUYS_EXISTS" -eq 0 ] && echo "$SCRAPER_CANADABUYS_CRON"
    [ "$SCRAPER_BONFIRE_EXISTS" -eq 0 ] && echo "$SCRAPER_BONFIRE_CRON"
    echo "------------------------------------------"
    echo ""
else
    echo "All required cron entries already exist."
    echo ""
    if [ "$APPLY" = true ]; then
        echo "No changes needed."
        exit 0
    fi
fi

if [ "$APPLY" = false ]; then
    echo "=========================================="
    echo "DRY RUN MODE (--print-only)"
    echo "=========================================="
    echo ""
    echo "To actually install these cron entries, run:"
    echo "  bash $0 --apply"
    echo ""
    echo "Current crontab:"
    echo "------------------------------------------"
    crontab -l 2>/dev/null || echo "(empty)"
    echo "------------------------------------------"
    echo ""
    echo "After applying (preview):"
    echo "------------------------------------------"
    echo "$NEW_CRONTAB"
    echo "------------------------------------------"
    exit 0
fi

# Apply changes
echo "=========================================="
echo "APPLYING CHANGES"
echo "=========================================="
echo ""
echo "Installing cron entries..."

echo "$NEW_CRONTAB" | crontab -

echo "  ✓ Crontab updated"
echo ""

# Verify
echo "Final crontab:"
echo "------------------------------------------"
crontab -l
echo "------------------------------------------"
echo ""

echo "=========================================="
echo "Installation Complete"
echo "=========================================="
echo ""
echo "Soak test cron entries installed successfully."
echo ""
echo "Schedule:"
echo "  - Daily backup: 2:00am"
echo "  - Weekly cleanup: Sunday 3:00am"
echo "  - CanadaBuys CSV: Every 6 hours (0:00, 6:00, 12:00, 18:00)"
echo "  - Bonfire JSON: Every 6 hours (0:30, 6:30, 12:30, 18:30)"
echo ""
echo "Next steps:"
echo "  1. Wait for first scraper runs (next 6-hour boundary)"
echo "  2. Monitor daily: bash scripts/check_soak_test_health.sh"
echo "  3. Check specific source: bash scripts/check_soak_test_health.sh canadabuys_csv"
echo "  4. Disable if needed: bash scripts/disable_soak_test_cron.sh --apply"
echo ""
