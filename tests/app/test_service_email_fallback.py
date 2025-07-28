from app.feature_flags import FeatureFlag, is_feature_enabled


def test_service_allow_fallback_defaults_to_false(sample_service):
    """Test that the allow_fallback field defaults to False"""
    service = sample_service()
    assert not service.allow_fallback


def test_service_email_fallback_feature_flag_is_disabled_by_default(mocker):
    """Test that the SERVICE_EMAIL_FALLBACK_ENABLED feature flag is disabled by default"""
    mocker.patch.dict('os.environ', {}, clear=True)
    assert not is_feature_enabled(FeatureFlag.SERVICE_EMAIL_FALLBACK_ENABLED)


def test_service_email_fallback_feature_flag_can_be_enabled(mocker):
    """Test that the SERVICE_EMAIL_FALLBACK_ENABLED feature flag can be enabled"""
    mocker.patch.dict('os.environ', {'SERVICE_EMAIL_FALLBACK_ENABLED': 'True'})
    assert is_feature_enabled(FeatureFlag.SERVICE_EMAIL_FALLBACK_ENABLED)
