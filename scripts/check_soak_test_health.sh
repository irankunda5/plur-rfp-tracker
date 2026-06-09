#!/usr/bin/env bash
# Soak Test Health Check
# Daily monitoring script for v2 multi-source soak test

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DB_PATH="$PROJECT_DIR/data/rfp.db"
BACKUP_DIR="$PROJECT_DIR/data/backups"
LOG_FILE="$PROJECT_DIR/logs/rfp_tracker.log"

# Parse arguments
SOURCE="all"
if [ $# -gt 0 ]; then
    SOURCE="$1"
fi

# Validate source argument
if [ "$SOURCE" != "all" ] && [ "$SOURCE" != "canadabuys_csv" ] && [ "$SOURCE" != "bonfire_json" ]; then
    echo "ERROR: Invalid source: $SOURCE"
    echo "Usage: $0 [all|canadabuys_csv|bonfire_json]"
    exit 1
fi

# Determine which sources to check
if [ "$SOURCE" = "all" ]; then
    SOURCES=("canadabuys_csv" "bonfire_json")
else
    SOURCES=("$SOURCE")
fi

# Health check results
WARNINGS=0
FAILURES=0

echo "=========================================="
echo "Soak Test Health Check"
echo "=========================================="
echo "Date: $(date)"
echo "Checking: ${SOURCES[*]}"
echo ""

# ========================================
# Check 1: Database exists
# ========================================
echo "[1/8] Database Status"
if [ -f "$DB_PATH" ]; then
    DB_SIZE=$(ls -lh "$DB_PATH" | awk '{print $5}')
    echo "  ✓ Database exists: $DB_SIZE"
else
    echo "  ✗ FAIL: Database not found at $DB_PATH"
    FAILURES=$((FAILURES + 1))
fi
echo ""

# ========================================
# Check 2: Latest backup exists
# ========================================
echo "[2/8] Backup Status"
LATEST_BACKUP=$(ls -t "$BACKUP_DIR"/rfp_*.db 2>/dev/null | head -1)
if [ -n "$LATEST_BACKUP" ]; then
    BACKUP_DATE=$(basename "$LATEST_BACKUP" | sed 's/rfp_//' | sed 's/.db//')
    BACKUP_AGE=$(( ($(date +%s) - $(date -j -f "%Y%m%d" "$BACKUP_DATE" +%s 2>/dev/null || echo 0)) / 86400 ))
    echo "  Latest backup: $BACKUP_DATE ($BACKUP_AGE days ago)"

    # Verify backup integrity
    if sqlite3 "$LATEST_BACKUP" "PRAGMA integrity_check;" 2>/dev/null | grep -q "ok"; then
        echo "  ✓ Backup integrity: OK"
    else
        echo "  ⚠ WARN: Backup integrity check failed"
        WARNINGS=$((WARNINGS + 1))
    fi

    if [ "$BACKUP_AGE" -gt 2 ]; then
        echo "  ⚠ WARN: Backup is $BACKUP_AGE days old (expected daily)"
        WARNINGS=$((WARNINGS + 1))
    fi
else
    echo "  ⚠ WARN: No backups found"
    WARNINGS=$((WARNINGS + 1))
fi
echo ""

# ========================================
# Check 3: Recent runs (last 5 per source)
# ========================================
echo "[3/8] Recent Runs (Last 5 per source)"
if [ -f "$DB_PATH" ]; then
    for src in "${SOURCES[@]}"; do
        echo ""
        echo "  Source: $src"
        echo "  -----------------------------------------"
        sqlite3 "$DB_PATH" "
            SELECT
                id,
                datetime(start_time, 'localtime') as start,
                ROUND((julianday(end_time) - julianday(start_time)) * 86400, 2) as duration_sec,
                records_found,
                records_new,
                status
            FROM source_runs
            WHERE source = '$src'
            ORDER BY id DESC
            LIMIT 5;
        " -header -column 2>/dev/null || echo "  ⚠ WARN: Could not query source_runs for $src"
    done
else
    echo "  ✗ FAIL: Database not found"
    FAILURES=$((FAILURES + 1))
fi
echo ""

# ========================================
# Check 4: 7-Day Success Rate (per source)
# ========================================
echo "[4/8] 7-Day Success Rate (per source)"
if [ -f "$DB_PATH" ]; then
    for src in "${SOURCES[@]}"; do
        echo ""
        echo "  Source: $src"
        echo "  -----------------------------------------"
        STATS=$(sqlite3 "$DB_PATH" "
            SELECT
                COUNT(*) as total_runs,
                SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as successful_runs,
                SUM(CASE WHEN status != 'success' THEN 1 ELSE 0 END) as failed_runs,
                ROUND(AVG((julianday(end_time) - julianday(start_time)) * 86400), 2) as avg_duration_sec
            FROM source_runs
            WHERE source = '$src'
              AND start_time >= datetime('now', '-7 days');
        " 2>/dev/null)

        TOTAL=$(echo "$STATS" | cut -d'|' -f1)
        SUCCESS=$(echo "$STATS" | cut -d'|' -f2)
        FAILED=$(echo "$STATS" | cut -d'|' -f3)
        AVG_DURATION=$(echo "$STATS" | cut -d'|' -f4)

        if [ "$TOTAL" -gt 0 ]; then
            SUCCESS_RATE=$(awk "BEGIN {printf \"%.1f\", ($SUCCESS / $TOTAL) * 100}")
            echo "  Total runs: $TOTAL"
            echo "  Successful: $SUCCESS ($SUCCESS_RATE%)"
            echo "  Failed: $FAILED"
            echo "  Avg duration: ${AVG_DURATION}s"

            if (( $(echo "$SUCCESS_RATE < 95.0" | bc -l) )); then
                echo "  ⚠ WARN: Success rate below 95% threshold"
                WARNINGS=$((WARNINGS + 1))
            else
                echo "  ✓ Success rate acceptable"
            fi

            if (( $(echo "$AVG_DURATION > 5.0" | bc -l) )); then
                echo "  ⚠ WARN: Average duration exceeds 5s threshold"
                WARNINGS=$((WARNINGS + 1))
            fi
        else
            echo "  ℹ No runs in last 7 days"
        fi
    done
else
    echo "  ✗ FAIL: Database not found"
    FAILURES=$((FAILURES + 1))
fi
echo ""

# ========================================
# Check 5: Recent Failures (per source)
# ========================================
echo "[5/8] Recent Failures (if any, per source)"
if [ -f "$DB_PATH" ]; then
    for src in "${SOURCES[@]}"; do
        echo ""
        echo "  Source: $src"
        echo "  -----------------------------------------"
        RECENT_FAILURES=$(sqlite3 "$DB_PATH" "
            SELECT COUNT(*)
            FROM source_runs
            WHERE source = '$src'
              AND status != 'success'
              AND start_time >= datetime('now', '-7 days');
        " 2>/dev/null)

        if [ "$RECENT_FAILURES" -gt 0 ]; then
            echo "  ⚠ WARN: $RECENT_FAILURES failures in last 7 days"
            WARNINGS=$((WARNINGS + 1))
            echo ""
            echo "  Latest failures:"
            sqlite3 "$DB_PATH" "
                SELECT
                    datetime(start_time, 'localtime') as time,
                    status,
                    error_message
                FROM source_runs
                WHERE source = '$src'
                  AND status != 'success'
                ORDER BY id DESC
                LIMIT 3;
            " -header -column 2>/dev/null || true
        else
            echo "  ✓ No failures in last 7 days"
        fi
    done
else
    echo "  ✗ FAIL: Database not found"
    FAILURES=$((FAILURES + 1))
fi
echo ""

# ========================================
# Check 6: Record Count (per source)
# ========================================
echo "[6/8] Current Record Count (per source)"
if [ -f "$DB_PATH" ]; then
    for src in "${SOURCES[@]}"; do
        RECORD_COUNT=$(sqlite3 "$DB_PATH" "
            SELECT COUNT(*)
            FROM notices
            WHERE source = '$src';
        " 2>/dev/null)
        echo "  $src: $RECORD_COUNT records"

        if [ "$RECORD_COUNT" -eq 0 ]; then
            echo "    ⚠ WARN: No records found (expected some after scraping)"
            WARNINGS=$((WARNINGS + 1))
        fi
    done
else
    echo "  ✗ FAIL: Database not found"
    FAILURES=$((FAILURES + 1))
fi
echo ""

# ========================================
# Check 7: Log File Errors
# ========================================
echo "[7/8] Log File Errors (Last 20)"
ERROR_COUNT=0
if [ -f "$LOG_FILE" ]; then
    ERRORS=$(grep -i "traceback\|error\|exception" "$LOG_FILE" 2>/dev/null | tail -20 || echo "")
    ERROR_COUNT=$(echo "$ERRORS" | grep -c "." || echo "0")

    if [ "$ERROR_COUNT" -gt 0 ]; then
        echo "  ⚠ WARN: Found $ERROR_COUNT error lines in last 20 matches"
        WARNINGS=$((WARNINGS + 1))
        echo ""
        echo "  Sample errors:"
        echo "$ERRORS" | head -5
    else
        echo "  ✓ No recent errors in logs"
    fi
else
    echo "  ℹ Log file not found: $LOG_FILE"
fi
echo ""

# ========================================
# Check 8: Cron Log Status (per source)
# ========================================
echo "[8/8] Cron Log Status (per source)"
for src in "${SOURCES[@]}"; do
    CRON_LOG="$PROJECT_DIR/logs/${src}_cron.log"
    echo ""
    echo "  Source: $src"
    echo "  -----------------------------------------"
    if [ -f "$CRON_LOG" ]; then
        CRON_SIZE=$(ls -lh "$CRON_LOG" | awk '{print $5}')
        CRON_LINES=$(wc -l < "$CRON_LOG")
        echo "  Cron log: $CRON_SIZE ($CRON_LINES lines)"

        # Check for recent activity
        LAST_MODIFIED=$(date -r "$CRON_LOG" "+%Y-%m-%d %H:%M:%S" 2>/dev/null || echo "unknown")
        echo "  Last modified: $LAST_MODIFIED"

        # Check for errors in cron log
        CRON_ERRORS=$(grep -c -i "error\|exception\|traceback" "$CRON_LOG" 2>/dev/null || echo "0")
        if [ "$CRON_ERRORS" -gt 0 ]; then
            echo "  ⚠ WARN: Found $CRON_ERRORS error lines in cron log"
            WARNINGS=$((WARNINGS + 1))
        else
            echo "  ✓ No errors in cron log"
        fi
    else
        echo "  ℹ Cron log not found (may not have run yet)"
    fi
done
echo ""

# ========================================
# Summary
# ========================================
echo "=========================================="
echo "Health Check Summary"
echo "=========================================="
echo ""

if [ "$FAILURES" -gt 0 ]; then
    echo "Status: ✗ FAIL"
    echo "Critical failures: $FAILURES"
    echo ""
    echo "ACTION REQUIRED: Investigate failures immediately."
    exit 2
elif [ "$WARNINGS" -gt 0 ]; then
    echo "Status: ⚠ WARN"
    echo "Warnings: $WARNINGS"
    echo ""
    echo "ACTION SUGGESTED: Review warnings and monitor."
    exit 1
else
    echo "Status: ✓ PASS"
    echo ""
    echo "All checks passed. Soak test is healthy."
    exit 0
fi
