#!/usr/bin/env bash
# Disable Soak Test Cron
# Safely disable v2 multi-source soak test cron entries (CanadaBuys + Bonfire)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Default to print-only mode (safe)
APPLY=false
DISABLE_BACKUPS=false

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
        --disable-backups)
            DISABLE_BACKUPS=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--print-only|--apply] [--disable-backups]"
            exit 1
            ;;
    esac
done

echo "=========================================="
echo "Soak Test Cron Disabler"
echo "=========================================="
echo ""

# Get current crontab
CURRENT_CRONTAB=$(crontab -l 2>/dev/null || echo "")

if [ -z "$CURRENT_CRONTAB" ]; then
    echo "No crontab entries found. Nothing to disable."
    exit 0
fi

echo "Current crontab:"
echo "------------------------------------------"
echo "$CURRENT_CRONTAB"
echo "------------------------------------------"
echo ""

# Build new crontab by commenting out v2 scraper entries
NEW_CRONTAB=$(echo "$CURRENT_CRONTAB" | while IFS= read -r line; do
    # Comment out v2 scraper lines
    if echo "$line" | grep -q "V2_SOURCES=canadabuys_csv.*run.py\|V2_SOURCES=bonfire_json.*run.py"; then
        echo "# DISABLED $(date +%Y-%m-%d) - $line"
    # Optionally comment out backup lines
    elif [ "$DISABLE_BACKUPS" = true ] && echo "$line" | grep -q "rfp_tracker.*backup\|rfp_tracker.*backups.*mtime"; then
        echo "# DISABLED $(date +%Y-%m-%d) - $line"
    else
        echo "$line"
    fi
done)

# Check if any changes were made
if [ "$CURRENT_CRONTAB" = "$NEW_CRONTAB" ]; then
    echo "No v2 soak test cron entries found to disable."
    echo ""
    if [ "$DISABLE_BACKUPS" = false ]; then
        echo "Note: Backup entries are left enabled by default."
        echo "To disable backups too, use: $0 --apply --disable-backups"
    fi
    exit 0
fi

echo "Changes to be made:"
echo "------------------------------------------"
echo "$NEW_CRONTAB"
echo "------------------------------------------"
echo ""

if [ "$APPLY" = false ]; then
    echo "=========================================="
    echo "DRY RUN MODE (--print-only)"
    echo "=========================================="
    echo ""
    echo "To actually disable v2 soak test cron entries, run:"
    echo "  bash $0 --apply"
    echo ""
    if [ "$DISABLE_BACKUPS" = false ]; then
        echo "Note: Backup entries will remain enabled (recommended)."
        echo "To disable backups too: bash $0 --apply --disable-backups"
    fi
    exit 0
fi

# Apply changes
echo "=========================================="
echo "APPLYING CHANGES"
echo "=========================================="
echo ""
echo "Disabling v2 soak test cron entries..."

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
echo "Soak Test Disabled"
echo "=========================================="
echo ""
echo "V2 scraper cron entries have been disabled."
echo ""
if [ "$DISABLE_BACKUPS" = false ]; then
    echo "Backup cron entries remain active (recommended)."
else
    echo "Backup cron entries have also been disabled."
fi
echo ""
echo "To re-enable the soak test, run:"
echo "  bash scripts/install_soak_test_cron.sh --apply"
echo ""
