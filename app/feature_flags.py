from enum import Enum
import os


PROVIDER_FEATURE_FLAGS = {
    'govdelivery': 'GOVDELIVERY_EMAIL_CLIENT_ENABLED'
}


class FeatureFlag(Enum):
    ACCEPT_RECIPIENT_IDENTIFIERS_ENABLED = 'ACCEPT_RECIPIENT_IDENTIFIERS_ENABLED'
    TEMPLATE_SERVICE_PROVIDERS_ENABLED = 'TEMPLATE_SERVICE_PROVIDERS_ENABLED'
    PROVIDER_STRATEGIES_ENABLED = 'PROVIDER_STRATEGIES_ENABLED'
    PINPOINT_RECEIPTS_ENABLED = 'PINPOINT_RECEIPTS_ENABLED'
    PINPOINT_INBOUND_SMS_ENABLED = 'PINPOINT_INBOUND_SMS_ENABLED'
    NOTIFICATION_FAILURE_REASON_ENABLED = 'NOTIFICATION_FAILURE_REASON_ENABLED'
    GITHUB_LOGIN_ENABLED = 'GITHUB_LOGIN_ENABLED'
    EMAIL_PASSWORD_LOGIN_ENABLED = 'EMAIL_PASSWORD_LOGIN_ENABLED'


def is_provider_enabled(current_app, provider_identifier):
    if provider_identifier in PROVIDER_FEATURE_FLAGS:
        return current_app.config.get(PROVIDER_FEATURE_FLAGS[provider_identifier])
    else:
        return True


def accept_recipient_identifiers_enabled():
    return is_feature_enabled(FeatureFlag.ACCEPT_RECIPIENT_IDENTIFIERS_ENABLED)


def is_gapixel_enabled(current_app):
    return current_app.config.get('GOOGLE_ANALYTICS_ENABLED')


def is_feature_enabled(feature_flag):
    if isinstance(feature_flag, FeatureFlag):
        return os.getenv(feature_flag.value, 'False') == 'True'
    return False
