"""Tests for the get_secret_generator helper function."""

from uuid import UUID

from app.constants import SECRET_TYPE_DEFAULT, SECRET_TYPE_UUID
from app.service.rest import get_secret_generator


def test_get_secret_generator_with_uuid_returns_uuid_generator():
    """Test that requesting 'uuid' secret type returns a function that generates UUIDs."""
    generator = get_secret_generator(SECRET_TYPE_UUID)

    assert generator is not None
    assert callable(generator)

    # Test that the generator produces valid UUID strings
    secret = generator()
    assert isinstance(secret, str)
    assert len(secret) == 36  # Standard UUID string length

    # Verify it's a valid UUID by parsing it
    parsed_uuid = UUID(secret)
    assert str(parsed_uuid) == secret


def test_get_secret_generator_with_default_returns_default_generator():
    """Test that requesting 'default' secret type returns a function that generates default tokens."""
    generator = get_secret_generator(SECRET_TYPE_DEFAULT)

    assert generator is not None
    assert callable(generator)

    # Test that the generator produces a string secret similar to the default behavior
    secret = generator()
    assert isinstance(secret, str)
    assert len(secret) >= 86  # Default token_urlsafe(64) generates ~86+ chars

    # Verify it's not a UUID format
    try:
        UUID(secret)
        assert False, 'Default secret should not be a valid UUID'
    except ValueError:
        pass  # Expected - default secrets are not UUIDs


def test_get_secret_generator_with_none_returns_none():
    """Test that requesting None secret type returns None."""
    generator = get_secret_generator(None)
    assert generator is None


def test_get_secret_generator_with_empty_string_returns_none():
    """Test that requesting empty string secret type returns None."""
    generator = get_secret_generator('')
    assert generator is None


def test_get_secret_generator_with_unknown_type_returns_none():
    """Test that requesting unknown secret type returns None."""
    generator = get_secret_generator('unknown_type')
    assert generator is None


def test_get_secret_generator_uuid_produces_unique_values():
    """Test that the UUID generator produces unique values on each call."""
    generator = get_secret_generator(SECRET_TYPE_UUID)

    # Generate multiple UUIDs and ensure they're all different
    secrets = [generator() for _ in range(10)]
    assert len(set(secrets)) == 10  # All should be unique

    # Verify all are valid UUIDs
    for secret in secrets:
        UUID(secret)  # This will raise ValueError if invalid


def test_get_secret_generator_default_produces_unique_values():
    """Test that the default generator produces unique values on each call."""
    generator = get_secret_generator(SECRET_TYPE_DEFAULT)

    # Generate multiple secrets and ensure they're all different
    secrets = [generator() for _ in range(10)]
    assert len(set(secrets)) == 10  # All should be unique

    # Verify all have expected length
    for secret in secrets:
        assert len(secret) >= 86
