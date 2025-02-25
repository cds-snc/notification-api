/*
 * This query is used to calculate the maximum sustained email and sms send rate per minute.
 * Here "sustained" means the average sent per minute over five minutes.
 */
with data as (
    select id,
        sent_at,
        sent_at::date as day,
        round_minutes(sent_at, 5) as sent_minute,
        (
            case
                when notification_type = 'email' then 1
                else 0
            end
        ) as num_emails,
        (
            case
                when notification_type = 'sms' then 1
                else 0
            end
        ) as num_sms
    from notifications
    where sent_at is not null
        and sent_at >= CURRENT_DATE - INTERVAL '7 days'
        and extract(
            dow
            from sent_at
        ) in (2, 3, 4, 5)
),
rollup as (
    select day,
        sent_minute,
        sum(num_emails) / 5 as emails_per_minute,
        sum(num_sms) / 5 as sms_per_minute
    from data
    group by day,
        sent_minute
)
select day,
    max(emails_per_minute) as sustained_emails_per_minute,
    max(sms_per_minute) as sustained_sms_per_minute
from rollup
group by day
order by day