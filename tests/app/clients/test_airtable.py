from datetime import datetime
from unittest.mock import Mock, patch

import pytest

from app.clients.airtable.models import AirtableTableMixin, NewsletterSubscriber
from tests.conftest import set_config_values


@pytest.fixture
def mock_test_airtable_model():
    """Create a TestModel with mocked meta for AirtableTableMixin tests."""
    mock_meta = Mock()
    mock_meta.table_name = "Test Table"
    mock_base = Mock()
    mock_meta.base = mock_base

    class TestModel(AirtableTableMixin):
        meta = mock_meta

        class Meta:
            table_name = "Test Table"
            base = mock_base

    return TestModel


class TestAirtableTableMixin:
    def test_table_exists_no_meta_attribute(self):
        """Test table_exists raises AttributeError when no Meta attribute."""

        class TestModel(AirtableTableMixin):
            pass

        with pytest.raises(AttributeError, match="Model must have a Meta attribute"):
            TestModel.table_exists()

    def test_table_exists_table_found(self, mock_test_airtable_model):
        """Test table_exists returns True when table is found."""
        mock_table = Mock()
        mock_table.name = "Test Table"
        mock_test_airtable_model.Meta.base.tables.return_value = [mock_table]

        assert mock_test_airtable_model.table_exists() is True

    def test_table_exists_table_not_found(self, mock_test_airtable_model):
        """Test table_exists returns False when table is not found."""
        mock_table = Mock()
        mock_table.name = "Other Table"
        mock_test_airtable_model.Meta.base.tables.return_value = [mock_table]

        assert mock_test_airtable_model.table_exists() is False

    def test_get_table_schema_not_implemented(self):
        """Test get_table_schema raises NotImplementedError."""
        with pytest.raises(NotImplementedError, match="Subclasses must implement get_table_schema"):
            AirtableTableMixin.get_table_schema()

    def test_create_table_n_meta_attribute(self):
        """Test create_table raises AttributeError when no meta attribute."""

        class TestModel(AirtableTableMixin):
            pass

        with pytest.raises(AttributeError, match="Model must have a meta attribute"):
            TestModel.create_table()

    def test_create_table_success(self, mocker):
        """Test create_table creates table successfully."""
        mock_schema = {"name": "Test Table", "fields": []}

        class TestModel(AirtableTableMixin):
            class meta:
                base = Mock()

            @classmethod
            def get_table_schema(cls):
                return mock_schema

        TestModel.create_table()
        TestModel.meta.base.create_table.assert_called_once_with("Test Table", fields=[])


class TestNewsletterSubscriber:
    def test_init_creates_table_if_not_exists(self, notify_api, mocker):
        """Test initialization creates table if it doesn't exist."""
        mocker.patch.object(NewsletterSubscriber, "table_exists", return_value=False)
        mock_create_table = mocker.patch.object(NewsletterSubscriber, "create_table")
        mocker.patch("pyairtable.orm.Model.save", return_value=Mock())
        sub = NewsletterSubscriber(email="test@example.com")
        sub.save()

        mock_create_table.assert_called_once()

    def test_init_default_values(self):
        """Test initialization with default values."""
        subscriber = NewsletterSubscriber(email="test@example.com")

        assert subscriber.language == NewsletterSubscriber.Languages.EN.value
        assert subscriber.status == NewsletterSubscriber.Statuses.UNCONFIRMED.value

    def test_from_email_success(self, mocker):
        """Test from_email returns subscriber when found."""
        mock_subscriber = Mock()
        mock_all = mocker.patch.object(NewsletterSubscriber, "all", return_value=[mock_subscriber])

        result = NewsletterSubscriber.from_email("test@example.com")

        assert result == mock_subscriber
        mock_all.assert_called_once_with(formula="{Email} = 'test@example.com'")

    def test_from_email_not_found(self, mocker):
        """Test from_email raises HTTPError when not found."""
        from requests import HTTPError

        mocker.patch.object(NewsletterSubscriber, "all", return_value=[])

        with pytest.raises(HTTPError) as exc_info:
            NewsletterSubscriber.from_email("test@example.com")

        assert exc_info.value.response.status_code == 404

    def test_from_email_exception_handling(self, mocker, notify_api):
        """Test from_email lets exceptions propagate."""
        mocker.patch.object(NewsletterSubscriber, "all", side_effect=Exception("Database error"))

        with pytest.raises(Exception, match="Database error"):
            NewsletterSubscriber.from_email("test@example.com")

    def test_save_unconfirmed_subscriber(self, mocker, notify_api):
        """Test save_unconfirmed_subscriber sets correct values and calls save."""
        subscriber = NewsletterSubscriber(email="test@example.com")
        mock_save = mocker.Mock(return_value="save_result")
        subscriber.save = mock_save

        result = subscriber.save_unconfirmed_subscriber()

        assert subscriber.status == NewsletterSubscriber.Statuses.UNCONFIRMED.value
        assert isinstance(subscriber.created_at, datetime)
        assert result == "save_result"
        mock_save.assert_called_once()

    def test_confirm_subscription(self):
        """Test confirm_subscription updates status and sets confirmed_at."""
        subscriber = NewsletterSubscriber(email="test@example.com")
        mock_save = Mock(return_value="save_result")
        subscriber.save = mock_save

        result = subscriber.confirm_subscription()

        assert subscriber.status == NewsletterSubscriber.Statuses.SUBSCRIBED.value
        assert isinstance(subscriber.confirmed_at, datetime)
        assert result == "save_result"
        mock_save.assert_called_once()

    def test_unsubscribe_user(self):
        """Test unsubscribe_user updates status and sets unsubscribed timestamp."""
        subscriber = NewsletterSubscriber(email="test@example.com")
        subscriber.confirmed_at = datetime.now()
        mock_save = Mock(return_value="save_result")
        subscriber.save = mock_save

        result = subscriber.unsubscribe_user()

        assert subscriber.status == NewsletterSubscriber.Statuses.UNSUBSCRIBED.value
        assert isinstance(subscriber.unsubscribed_at, datetime)
        assert subscriber.confirmed_at is None
        assert result == "save_result"
        mock_save.assert_called_once()

    def test_update_language_success(self):
        """Test update_language updates language successfully."""
        subscriber = NewsletterSubscriber(email="test@example.com")
        subscriber.status = NewsletterSubscriber.Statuses.SUBSCRIBED.value
        mock_save = Mock(return_value="save_result")
        subscriber.save = mock_save

        # Mock the Languages enum __contains__ method
        with patch.object(NewsletterSubscriber.Languages, "__contains__", return_value=True):
            result = subscriber.update_language("fr")

        assert subscriber.language == "fr"
        assert result == "save_result"
        mock_save.assert_called_once()

    def test_reactivate_subscription(self):
        """Test reactivate_subscription reactivates unsubscribed user."""
        subscriber = NewsletterSubscriber(email="test@example.com")
        mock_save = Mock(return_value="save_result")
        subscriber.save = mock_save

        result = subscriber.reactivate_subscription("fr")

        assert subscriber.status == NewsletterSubscriber.Statuses.SUBSCRIBED.value
        assert subscriber.language == "fr"
        assert subscriber.has_resubscribed is True
        assert result == "save_result"
        mock_save.assert_called_once()

    def test_get_table_schema_structure(self, notify_api):
        """Test get_table_schema returns correct schema structure."""
        schema = NewsletterSubscriber.get_table_schema()

        assert schema["name"] == NewsletterSubscriber.Meta.table_name()
        assert len(schema["fields"]) == 7

        field_names = [field["name"] for field in schema["fields"]]
        expected_fields = ["Email", "Language", "Status", "Created At", "Confirmed At", "Unsubscribed At", "Has Resubscribed"]

        for field_name in expected_fields:
            assert field_name in field_names

    def test_get_table_schema_language_choices(self):
        """Test get_table_schema includes correct language choices."""
        schema = NewsletterSubscriber.get_table_schema()

        language_field = next(field for field in schema["fields"] if field["name"] == "Language")
        choices = [choice["name"] for choice in language_field["options"]["choices"]]

        assert NewsletterSubscriber.Languages.EN.value in choices
        assert NewsletterSubscriber.Languages.FR.value in choices

    def test_get_table_schema_status_choices(self):
        """Test get_table_schema includes correct status choices."""
        schema = NewsletterSubscriber.get_table_schema()

        status_field = next(field for field in schema["fields"] if field["name"] == "Status")
        choices = [choice["name"] for choice in status_field["options"]["choices"]]

        assert NewsletterSubscriber.Statuses.UNCONFIRMED.value in choices
        assert NewsletterSubscriber.Statuses.SUBSCRIBED.value in choices
        assert NewsletterSubscriber.Statuses.UNSUBSCRIBED.value in choices

    def test_languages_enum_values(self):
        """Test Languages enum has correct values."""
        assert NewsletterSubscriber.Languages.EN.value == "en"
        assert NewsletterSubscriber.Languages.FR.value == "fr"

    def test_statuses_enum_values(self):
        """Test Statuses enum has correct values."""
        assert NewsletterSubscriber.Statuses.UNCONFIRMED.value == "unconfirmed"
        assert NewsletterSubscriber.Statuses.SUBSCRIBED.value == "subscribed"
        assert NewsletterSubscriber.Statuses.UNSUBSCRIBED.value == "unsubscribed"

    def test_meta_class_environment_variables(self, notify_api, mocker):
        """Test Meta class reads environment variables correctly."""

        # Ensure the Meta class uses the test app instance
        mocker.patch.object(NewsletterSubscriber, "_flask_app", notify_api)

        with set_config_values(
            notify_api,
            {
                "AIRTABLE_API_KEY": "test_key",
                "AIRTABLE_NEWSLETTER_BASE_ID": "test_base",
                "AIRTABLE_NEWSLETTER_TABLE_NAME": "test_name",
            },
        ):
            assert NewsletterSubscriber.Meta.api_key() == "test_key"
            assert NewsletterSubscriber.Meta.base_id() == "test_base"
            assert NewsletterSubscriber.Meta.table_name() == "test_name"
