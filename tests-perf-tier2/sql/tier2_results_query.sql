/*
 * Tier 2 Performance Test — Post-test analysis.
 *
 * Computes end-to-end delivery statistics for notifications sent during a
 * performance test run, identified by the reference tag (e.g. 'tier2-L2-burst').
 *
 * Columns:
 *   - redis_time:      API POST → row created in notifications table
 *   - processing_time: created → sent to provider
 *   - delivery_time:   sent → delivery receipt (updated_at)
 *   - total_time:      API POST → delivery receipt
 *
 * Usage:
 *   Replace 'tier2-L2-burst' with your --ref value.
 */

WITH initial_data AS (
    SELECT
        n.id,
        n.notification_type,
        n.notification_status AS status,
        t.process_type AS priority,
        to_timestamp(
            split_part(n.client_reference, ' ', 1),
            'YYYY-MM-DD"T"HH24:MI:SS.US'
        ) AS posted_at,
        n.created_at,
        n.sent_at,
        n.updated_at
    FROM notifications n
    JOIN templates t ON n.template_id = t.id
    WHERE n.client_reference LIKE '%tier2-%'
),
timings AS (
    SELECT
        *,
        EXTRACT(epoch FROM updated_at - posted_at)  AS total_time,
        EXTRACT(epoch FROM created_at - posted_at)   AS redis_time,
        EXTRACT(epoch FROM sent_at - created_at)     AS processing_time,
        EXTRACT(epoch FROM updated_at - sent_at)     AS delivery_time
    FROM initial_data
)
SELECT
    notification_type,
    status,
    priority,
    count(*) AS count,
    round(percentile_cont(0.50) WITHIN GROUP (ORDER BY total_time)::numeric, 2)      AS total_p50,
    round(percentile_cont(0.95) WITHIN GROUP (ORDER BY total_time)::numeric, 2)      AS total_p95,
    round(percentile_cont(0.99) WITHIN GROUP (ORDER BY total_time)::numeric, 2)      AS total_p99,
    round(percentile_cont(0.50) WITHIN GROUP (ORDER BY redis_time)::numeric, 2)      AS redis_p50,
    round(percentile_cont(0.50) WITHIN GROUP (ORDER BY processing_time)::numeric, 2) AS processing_p50,
    round(percentile_cont(0.50) WITHIN GROUP (ORDER BY delivery_time)::numeric, 2)   AS delivery_p50
FROM timings
GROUP BY notification_type, status, priority
ORDER BY notification_type, status, priority;
