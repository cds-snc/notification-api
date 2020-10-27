PROVIDER_FEATURE_FLAGS = {
    'govdelivery': 'GOVDELIVERY_EMAIL_CLIENT_ENABLED'
}


def is_provider_enabled(current_app, provider_identifier):
    if provider_identifier in PROVIDER_FEATURE_FLAGS:
        return current_app.config.get(PROVIDER_FEATURE_FLAGS[provider_identifier])
    else:
        return True


def accept_recipient_identifiers_enabled(current_app):
    return current_app.config.get('ACCEPT_RECIPIENT_IDENTIFIERS_ENABLED', False)
