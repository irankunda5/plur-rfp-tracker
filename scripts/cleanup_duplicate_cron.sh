#!/usr/bin/env bash
# Cleanup Duplicate Cron Entries
# Removes exact duplicate lines from crontab while preserving all unique entries

set -e

echo "=========================================="
echo "Cron Duplicate Cleanup"
echo "=========================================="
echo ""

# Get current crontab
CURRENT=$(crontab -l 2>/dev/null || echo "")

if [ -z "$CURRENT" ]; then
    echo "No crontab entries found."
    exit 0
fi

echo "Current crontab ($( echo "$CURRENT" | wc -l | tr -d ' ') lines):"
echo "------------------------------------------"
echo "$CURRENT"
echo "------------------------------------------"
echo ""

# Deduplicate using awk (keeps first occurrence of each unique line)
DEDUPED=$(echo "$CURRENT" | awk '!seen[$0]++')
DEDUPED_LINES=$(echo "$DEDUPED" | wc -l | tr -d ' ')

# Count how many duplicates were removed
ORIGINAL_LINES=$(echo "$CURRENT" | wc -l | tr -d ' ')
REMOVED=$((ORIGINAL_LINES - DEDUPED_LINES))

if [ "$REMOVED" -eq 0 ]; then
    echo "✓ No duplicate lines found. Crontab is clean."
    exit 0
fi

echo "Found $REMOVED duplicate line(s)."
echo ""
echo "Cleaned crontab ($DEDUPED_LINES lines):"
echo "------------------------------------------"
echo "$DEDUPED"
echo "------------------------------------------"
echo ""

read -p "Apply cleaned crontab? (y/n): " -n 1 -r
echo

if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "$DEDUPED" | crontab -
    echo ""
    echo "✓ Crontab cleaned successfully"
    echo ""
    echo "Verification:"
    echo "------------------------------------------"
    crontab -l
    echo "------------------------------------------"
else
    echo "Cancelled. No changes made."
    exit 1
fi
