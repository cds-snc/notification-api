# GDS- and CDS-specific features to change

## Global config

- `API_RATE_LIMIT_ENABLED`: if set to True and Redis is enabled, will enforce rate limit. Default rate (per service) is 3000/min
    - Suggestion: set to False
- Daily message limit:  Required when creating a service. No global flag to enable/disable.
    - Suggestion: add global flag similar to rate limit, or rename `API_RATE_LIMIT_ENABLED` and use for both rate limit and message limit
- `SMS_CHAR_COUNT_LIMIT`: set to 612
- `DEFAULT_SERVICE_PERMISSIONS`: currently set to email, sms, and international sms. All the permission types are found [here](https://github.com/department-of-veterans-affairs/notification-api/blob/master/app/models.py#L310)

## notification-utils

Using [notification-utils](https://github.com/department-of-veterans-affairs/notification-utils).

## Crown

Organizations/Services have a `crown` flag. This is only used for letters (possibly for billing), doesn't affect SMS/email.

## Primary service and user
