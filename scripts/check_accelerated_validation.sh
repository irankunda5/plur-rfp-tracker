#!/usr/bin/env bash
# 72-Hour Accelerated Validation Report
# Focused health check for v2 multi-source production validation

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DB_PATH="$PROJECT_DIR/data/rfp.db"

# Validation start time (Post-fix baseline: 2026-05-17 16:47 PDT = 23:47 UTC)
# This excludes pre-fix failures (run_id=11, 13) and starts from first post-fix run (run_id=15)
VALIDATION_START="2026-05-17 23:47:00"

# 72-hour success criteria
EXPECTED_RUNS=12        # 4 runs/day × 3 days
MIN_SUCCESS_RATE=95.0   # 95% = 11/12 successful
MAX_AVG_DURATION=5.0    # seconds

echo "=========================================="
echo "72-Hour Accelerated Validation Report"
echo "=========================================="
echo "Validation started: $VALIDATION_START UTC (2026-05-17 16:47 PDT)"
echo "Current time:       $(date -u '+%Y-%m-%d %H:%M:%S') UTC"
echo ""

# Calculate hours elapsed using SQLite
HOURS_ELAPSED=$(sqlite3 "$DB_PATH" "
    SELECT CAST((julianday('now') - julianday('$VALIDATION_START')) * 24 AS INTEGER);
" 2>/dev/null || echo "0")

PROGRESS=$(awk "BEGIN {printf \"%.1f\", ($HOURS_ELAPSED / 72.0) * 100}")
echo "Hours elapsed: $HOURS_ELAPSED / 72"
echo "Progress: ${PROGRESS}%"
echo ""

# Overall validation status
OVERALL_STATUS="PASS"
WARNINGS=0
FAILURES=0

# Check each source
for SOURCE in "canadabuys_csv" "bonfire_json"; do
    echo "=========================================="
    echo "Source: $SOURCE"
    echo "=========================================="

    # Query runs since validation start
    STATS=$(sqlite3 "$DB_PATH" "
        SELECT
            COUNT(*) as total_runs,
            SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as successful,
            SUM(CASE WHEN status != 'success' THEN 1 ELSE 0 END) as failed,
            ROUND(AVG((julianday(end_time) - julianday(start_time)) * 86400), 2) as avg_duration,
            SUM(records_found) as total_found,
            SUM(records_new) as total_new
        FROM source_runs
        WHERE source = '$SOURCE'
          AND datetime(start_time) >= datetime('$VALIDATION_START');
    " 2>/dev/null)

    TOTAL=$(echo "$STATS" | cut -d'|' -f1)
    SUCCESS=$(echo "$STATS" | cut -d'|' -f2)
    FAILED=$(echo "$STATS" | cut -d'|' -f3)
    AVG_DUR=$(echo "$STATS" | cut -d'|' -f4)
    TOTAL_FOUND=$(echo "$STATS" | cut -d'|' -f5)
    TOTAL_NEW=$(echo "$STATS" | cut -d'|' -f6)

    if [ "$TOTAL" -gt 0 ]; then
        SUCCESS_RATE=$(awk "BEGIN {printf \"%.1f\", ($SUCCESS / $TOTAL) * 100}")

        echo "Total runs: $TOTAL"
        echo "Successful: $SUCCESS ($SUCCESS_RATE%)"
        echo "Failed: $FAILED"
        echo "Avg duration: ${AVG_DUR}s"
        echo "Total records found: $TOTAL_FOUND"
        echo "Total records new: $TOTAL_NEW"
        echo ""

        # Expected runs (pro-rated based on hours elapsed)
        EXPECTED_NOW=$(awk "BEGIN {printf \"%.0f\", ($HOURS_ELAPSED / 6.0)}")
        echo "Expected runs: ~$EXPECTED_NOW (at current elapsed time)"

        if [ "$TOTAL" -lt "$((EXPECTED_NOW - 1))" ]; then
            echo "⚠ WARN: Significantly fewer runs than expected"
            WARNINGS=$((WARNINGS + 1))
        elif [ "$TOTAL" -lt "$EXPECTED_NOW" ]; then
            echo "ℹ INFO: Slightly fewer runs than expected (acceptable)"
        else
            echo "✓ Run count acceptable"
        fi
        echo ""

        # Evaluate success rate
        if (( $(echo "$SUCCESS_RATE < $MIN_SUCCESS_RATE" | bc -l) )); then
            echo "✗ FAIL: Success rate below ${MIN_SUCCESS_RATE}% threshold"
            FAILURES=$((FAILURES + 1))
            OVERALL_STATUS="FAIL"
        else
            echo "✓ Success rate meets threshold"
        fi
        echo ""

        # Evaluate avg duration
        if (( $(echo "$AVG_DUR > $MAX_AVG_DURATION" | bc -l) )); then
            echo "⚠ WARN: Average duration exceeds ${MAX_AVG_DURATION}s threshold"
            WARNINGS=$((WARNINGS + 1))
        else
            echo "✓ Average duration acceptable"
        fi
        echo ""

        # Recent failures (post-fix only)
        RECENT_FAILURES=$(sqlite3 "$DB_PATH" "
            SELECT COUNT(*)
            FROM source_runs
            WHERE source = '$SOURCE'
              AND status != 'success'
              AND datetime(start_time) >= datetime('$VALIDATION_START');
        " 2>/dev/null)

        if [ "$RECENT_FAILURES" -gt 0 ]; then
            echo "Failures since validation start ($RECENT_FAILURES):"
            sqlite3 "$DB_PATH" "
                SELECT
                    datetime(start_time, 'localtime') as time,
                    status,
                    error_message
                FROM source_runs
                WHERE source = '$SOURCE'
                  AND status != 'success'
                  AND start_time >= '$VALIDATION_START'
                ORDER BY id DESC;
            " -header -column 2>/dev/null
            echo ""
            WARNINGS=$((WARNINGS + 1))
        else
            echo "✓ No failures since validation start"
            echo ""
        fi

        # Latest run
        echo "Latest run:"
        sqlite3 "$DB_PATH" "
            SELECT
                datetime(start_time, 'localtime') as time,
                status,
                records_found,
                records_new,
                ROUND((julianday(end_time) - julianday(start_time)) * 86400, 2) as duration_sec
            FROM source_runs
            WHERE source = '$SOURCE'
            ORDER BY id DESC
            LIMIT 1;
        " -header -column 2>/dev/null
        echo ""

    else
        echo "✗ FAIL: No runs since validation start"
        FAILURES=$((FAILURES + 1))
        OVERALL_STATUS="FAIL"
        echo ""
    fi
done

# Check for duplicates
echo "=========================================="
echo "Duplicate Check"
echo "=========================================="

DUPLICATES=$(sqlite3 "$DB_PATH" "
    SELECT
        source,
        source_id,
        COUNT(*) as count
    FROM notices
    WHERE source IN ('canadabuys_csv', 'bonfire_json')
    GROUP BY source, source_id
    HAVING count > 1;
" 2>/dev/null)

if [ -z "$DUPLICATES" ]; then
    echo "✓ No duplicate records found"
else
    echo "✗ FAIL: Duplicate records detected:"
    echo "$DUPLICATES"
    FAILURES=$((FAILURES + 1))
    OVERALL_STATUS="FAIL"
fi
echo ""

# Summary
echo "=========================================="
echo "72-Hour Validation Criteria"
echo "=========================================="
echo "Per source requirements:"
echo "  - Total runs: $EXPECTED_RUNS (4/day × 3 days)"
echo "  - Success rate: ≥${MIN_SUCCESS_RATE}% (≥11/12 successful)"
echo "  - Avg duration: <${MAX_AVG_DURATION} seconds"
echo "  - No duplicate records"
echo ""
echo "Completion status:"
echo "  - Hours elapsed: $HOURS_ELAPSED / 72"
echo "  - Progress: ${PROGRESS}%"
if [ "$HOURS_ELAPSED" -ge 72 ]; then
    echo "  - Status: ✓ 72-hour window complete"
else
    REMAINING=$((72 - HOURS_ELAPSED))
    echo "  - Status: In progress ($REMAINING hours remaining)"
fi
echo ""

echo "=========================================="
echo "Validation Summary"
echo "=========================================="

if [ "$OVERALL_STATUS" = "FAIL" ]; then
    echo "Status: ✗ FAIL"
    echo "Failures: $FAILURES"
    echo "Warnings: $WARNINGS"
    echo ""
    echo "ACTION REQUIRED: Investigate failures before deployment."
    exit 1
elif [ "$WARNINGS" -gt 0 ]; then
    echo "Status: ⚠ WARN"
    echo "Warnings: $WARNINGS"
    echo ""
    echo "ACTION SUGGESTED: Review warnings before deployment."
    exit 0
else
    echo "Status: ✓ PASS"
    echo ""
    echo "Validation passing. Safe to proceed when 72h complete."
    exit 0
fi
