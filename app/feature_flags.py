from enum import Enum
import os


class FeatureFlag(Enum):
    ACCEPT_RECIPIENT_IDENTIFIERS_ENABLED = 'ACCEPT_RECIPIENT_IDENTIFIERS_ENABLED'
    TEMPLATE_SERVICE_PROVIDERS_ENABLED = 'TEMPLATE_SERVICE_PROVIDERS_ENABLED'
    PROVIDER_STRATEGIES_ENABLED = 'PROVIDER_STRATEGIES_ENABLED'
    PINPOINT_RECEIPTS_ENABLED = 'PINPOINT_RECEIPTS_ENABLED'
    PINPOINT_INBOUND_SMS_ENABLED = 'PINPOINT_INBOUND_SMS_ENABLED'
    NOTIFICATION_FAILURE_REASON_ENABLED = 'NOTIFICATION_FAILURE_REASON_ENABLED'
    GITHUB_LOGIN_ENABLED = 'GITHUB_LOGIN_ENABLED'
    EMAIL_PASSWORD_LOGIN_ENABLED = 'EMAIL_PASSWORD_LOGIN_ENABLED'  # nosec
    CHECK_GITHUB_SCOPE_ENABLED = 'CHECK_GITHUB_SCOPE_ENABLED'
    SMS_SENDER_RATE_LIMIT_ENABLED = 'SMS_SENDER_RATE_LIMIT_ENABLED'
    CHECK_TEMPLATE_NAME_EXISTS_ENABLED = 'CHECK_TEMPLATE_NAME_EXISTS_ENABLED'
    EMAIL_ATTACHMENTS_ENABLED = 'EMAIL_ATTACHMENTS_ENABLED'
    NIGHTLY_NOTIF_CSV_ENABLED = 'NIGHTLY_NOTIF_CSV_ENABLED'
    PUSH_NOTIFICATIONS_ENABLED = 'PUSH_NOTIFICATIONS_ENABLED'
    PLATFORM_STATS_ENABLED = 'PLATFORM_STATS_ENABLED'
    VA_SSO_ENABLED = 'VA_SSO_ENABLED'
    V3_ENABLED = 'V3_ENABLED'
    COMP_AND_PEN_MESSAGES_ENABLED = 'COMP_AND_PEN_MESSAGES_ENABLED'
    VA_PROFILE_EMAIL_STATUS_ENABLED = 'VA_PROFILE_EMAIL_STATUS_ENABLED'
    VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP = (
        'VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP'
    )
    VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS = 'VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS'


def accept_recipient_identifiers_enabled():
    return is_feature_enabled(FeatureFlag.ACCEPT_RECIPIENT_IDENTIFIERS_ENABLED)


def is_gapixel_enabled(current_app):
    return current_app.config.get('GOOGLE_ANALYTICS_ENABLED')


def is_feature_enabled(feature_flag):
    return isinstance(feature_flag, FeatureFlag) and os.getenv(feature_flag.value, 'False') == 'True'