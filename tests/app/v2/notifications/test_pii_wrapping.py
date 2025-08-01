import pytest
from unittest.mock import patch

from app.feature_flags import is_feature_enabled, FeatureFlag
from app.pii import PiiIcn, PiiEdipi, PiiBirlsid, PiiPid, PiiVaProfileID
from app.va.identifier import IdentifierType
from app.v2.notifications.post_notifications import wrap_recipient_identifier_in_pii


class TestPiiWrappingAtEntrypoint:
    """Tests for PII wrapping functionality at system entry point."""

    @pytest.mark.parametrize(
        'id_type,id_value,expected_pii_class',
        [
            (IdentifierType.ICN.value, '1234567890V123456', PiiIcn),
            (IdentifierType.EDIPI.value, '1234567890', PiiEdipi),
            (IdentifierType.BIRLSID.value, 'BIRLSID123', PiiBirlsid),
            (IdentifierType.PID.value, 'PID123456', PiiPid),
            (IdentifierType.VA_PROFILE_ID.value, '12345', PiiVaProfileID),
        ],
    )
    def test_wrap_recipient_identifier_all_types(self, notify_api, id_type, id_value, expected_pii_class):
        """Test that all identifier types are wrapped in their corresponding PII classes."""
        with notify_api.app_context():
            form = {'recipient_identifier': {'id_type': id_type, 'id_value': id_value}}

            result = wrap_recipient_identifier_in_pii(form)

            # id_type should remain unchanged
            assert result['recipient_identifier']['id_type'] == id_type
            # id_value should be wrapped in the expected PII class
            assert isinstance(result['recipient_identifier']['id_value'], expected_pii_class)
            assert result['recipient_identifier']['id_value'].get_pii() == id_value

    @pytest.mark.parametrize(
        'form',
        [
            {'template_id': 'some-template-id', 'phone_number': '555-123-4567'},
            {'recipient_identifier': {'id_type': 'UNKNOWN_TYPE', 'id_value': 'some_value'}},
        ],
        ids=[
            'no recipient_identifier',
            'unknown id_type',
        ],
    )
    def test_wrap_recipient_identifier_edge_cases(self, notify_api, form):
        """Test that edge cases are handled gracefully."""
        with notify_api.app_context():
            # Make a shallow copy since wrap_recipient_identifier_in_pii may modify the form in-place.
            original_form = form.copy()
            result = wrap_recipient_identifier_in_pii(form)

            # Form should be unchanged for all edge cases
            assert result == original_form

    def test_wrap_recipient_identifier_pii_instantiation_error(self, notify_api):
        """Test that PII instantiation errors are handled gracefully."""
        with notify_api.app_context():
            form = {'recipient_identifier': {'id_type': IdentifierType.ICN.value, 'id_value': 'bad_value'}}

            with patch(
                'app.v2.notifications.post_notifications.PiiIcn', side_effect=Exception('PII error')
            ) as mock_pii_icn:
                mock_pii_icn.__name__ = 'PiiIcn'
                result = wrap_recipient_identifier_in_pii(form)

            # Form should be unchanged if PII instantiation fails
            assert result['recipient_identifier']['id_type'] == IdentifierType.ICN.value
            assert result['recipient_identifier']['id_value'] == 'bad_value'


class TestPiiWrappingFeatureFlag:
    """Tests for the PII wrapping feature flag."""

    @pytest.mark.parametrize(
        'env_value,expected',
        [
            ({}, False),  # disabled by default
            ({'PII_ENABLED': 'True'}, True),  # can be enabled
            ({'PII_ENABLED': 'False'}, False),  # can be explicitly disabled
        ],
    )
    def test_pii_enabled_feature_flag(self, mocker, env_value, expected):
        """Test PII_ENABLED feature flag behavior."""
        mocker.patch.dict('os.environ', env_value, clear=True)

        assert is_feature_enabled(FeatureFlag.PII_ENABLED) == expected
