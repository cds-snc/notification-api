/*
 * This query is used to calculate the maximum sustained SMS send rate per minute.
 * Here "sustained" means the average sent per minute over five minutes.
 */
with data as (
    select id,
        sent_at,
        sent_at::date as day,
        round_minutes(sent_at, 5) as sent_minute
    from notifications
    where sent_at is not null
        and sent_at >= CURRENT_DATE - INTERVAL '7 days'
        and notification_type = 'sms'
),
rollup as (
    select day,
        sent_minute,
        count(*) / 5 as notifications_per_minute
    from data
    group by day,
        sent_minute
)
select day,
    max(notifications_per_minute) as sustained_sms_per_minute
from rollup
group by day