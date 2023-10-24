from app.models import BULK, NORMAL, PRIORITY

# Default retry policy for all notifications.
RETRY_POLICY_DEFAULT = {
    "max_retries": 48,
    "interval_start": 300,
    "interval_step": 300,
    "interval_max": 300,
    "retry_errors": None,
}

# Retry policy for high priority notifications.
RETRY_POLICY_HIGH = {
    "max_retries": 48,
    "interval_start": 25,
    "interval_step": 25,
    "interval_max": 25,
    "retry_errors": None,
}

# Retry policies for each notification priority lanes.
RETRY_POLICIES = {
    BULK: RETRY_POLICY_DEFAULT,
    NORMAL: RETRY_POLICY_DEFAULT,
    PRIORITY: RETRY_POLICY_HIGH,
}
