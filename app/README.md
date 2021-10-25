## Rate Limiting for SMS Sender
Users can set different rate limits and rate limit intervals for each SMS sender. Rate limit is defined as the number
of messages that can be sent by the SMS sender within the rate limit interval.

When a user wants to send a notification, we check to see if the SMS sender associated with the notification has a rate
limit. If they do, we have a specific task that attempts to deliver a text. The task will still go on the `send-sms`
queue.

In this `send-sms-with-rate-limiting` task, we use Redis to determine if the rate limit has been exceeded.
We first remove all entries from the Redis cache associated with the SMS sender id that are outside of the time interval
of our rate limit. We then add a new timestamp entry to the Redis cache, and determine how many entries have a timestamp
within a minute. If the number of entries are over the rate limit, we attempt to retry the delivery sms task in a certain
amount of time based on the rate limit (specifically, `rate_limit / rate_limit_interval`). The retry task is added to a
retry queue specifically for rate-limited tasks.

Note that the SMS sender rate limit is distinct from the rate limit set on a service. The service rate limit 
determines how many requests can be made to our API to send a notification, not the rate at which the SMSes are
actually sent out.

In order to update an SMS sender that already has a rate limit configured, set `rate_limit` and `rate_limit_interval`
to `null`.


## Getting Template Stats
Every day, the `create-nightly-notification-status-for-day` celery task runs which converts the notifications
from today into FactNotificationStatus objects and inserts them into the `ft_notification_status` table. The
`notifications` table does not keep Notifications older than a week, so the `ft_notification_status` table
needs to be queried to get older stats. As a result, the `get_specific_template_usage_stats()` method in
`template/rest.py` relies on a method, `fetch_template_usage_for_service_with_given_template()`, that first
queries the `ft_notification_status` table and then the `notifications` table if the user needs to get stats
from today.
