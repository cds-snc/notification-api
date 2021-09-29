## Rate Limiting for SMS Sender
Users can set different rate limits for each SMS sender. Rate limit is defined as the number of messages that can be
sent by the SMS sender every 60 seconds. When a user wants to send a notification, we check to see
if the SMS sender associated with the notification (whether passed into the request or pulled from the service's 
default SMS sender) has a rate limit. If they do, we have a specific task that attempts to deliver a text. Note that
the task will still go on the `send-sms` queue. In this task, we use Redis to determine if the rate limit has been 
exceeded. We add a new timestamp entry to the redis cache using the sms sender (aka phone number) as the cache key, and 
determine how many entries have a timestamp within a minute. If the number of entries are over the rate limit, we 
attempt to retry the delivery sms task in a certain amount of time based on the rate limit (specifically, rate limit 
divided by 1 minute). This retry task is added to a retry queue specifically for rate-limited tasks.

Note that the SMS sender rate limit is distinct from the rate limit set on a service. The service rate limit 
determines how many requests can be made to our API to send a notification, not the rate at which the SMSes are
actually sent out.
