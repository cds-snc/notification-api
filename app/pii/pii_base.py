"""Module for handling PII (Personally Identifiable Information) data.

This module provides a base class for safely handling PII data, preventing accidental
logging or exposure of sensitive information. It implements encryption for PII data
and provides controlled methods to access the actual values when needed.

Classes in this module follow guidance from:
- NIST 800-122
- NIST 800-53
- NIST 800-60
- VA Documents
"""

import os
from enum import Enum
from typing import ClassVar
from cryptography.fernet import Fernet

from app.va.identifier import IdentifierType


class PiiEncryption:
    """Singleton to manage encryption for PII data."""

    _instance: 'PiiEncryption | None' = None
    _key: bytes | None = None
    _fernet: Fernet | None = None

    def __new__(cls) -> 'PiiEncryption':
        if cls._instance is None:
            cls._instance = super(PiiEncryption, cls).__new__(cls)
        return cls._instance

    @classmethod
    def get_encryption(cls) -> Fernet:
        """Get or create a Fernet instance for encryption/decryption."""
        if cls._fernet is None:
            # Use environment variable or generate a new key
            # In production, this key should be managed securely
            key_str = os.environ.get('PII_ENCRYPTION_KEY')
            if key_str is None:
                cls._key = Fernet.generate_key()
            else:
                cls._key = key_str.encode() if isinstance(key_str, str) else key_str

            cls._fernet = Fernet(cls._key)
        return cls._fernet


class PiiLevel(Enum):
    """Enumeration of PII impact levels based on FIPS 199 and NIST 800-122."""

    LOW = 0  # Limited adverse effect
    MODERATE = 1  # Serious adverse effect
    HIGH = 2  # Severe or catastrophic adverse effect


class Pii(str):
    """Base class for handling PII data with automatic encryption and redaction.

    This class encrypts PII data upon initialization and provides controlled access
    methods to decrypt the data when needed. It also provides string representations
    that redact the data based on its impact level.

    Attributes:
        _level (ClassVar[PiiLevel]): The impact level of the PII data, defaults to HIGH.
            This class variable should be overridden in subclasses to define the
            appropriate PII level. It should not be modified after class definition.
    """

    _level: ClassVar[PiiLevel] = PiiLevel.HIGH
    _encrypted_value: str

    @property
    def level(self) -> PiiLevel:
        """Get the PII impact level for this class.

        This property accesses the class-level _level attribute and ensures
        that it cannot be modified at the instance level.

        Returns:
            PiiLevel: The PII impact level defined for this class
        """
        return self.__class__._level

    def __new__(cls, value: str, is_encrypted: bool = False) -> 'Pii':
        """Create a new Pii instance with encrypted value.
        The class name is used as the suffix after "redacted" in string representations

        Args:
            value (str): The PII value to encrypt.
            is_encrypted (bool): If this is already encrypted

        Returns:
            Pii: A new Pii instance (of a subclass) with the value encrypted.

        Raises:
            TypeError: If the `Pii` base class itself is being instantiated.
        """
        if cls is Pii:
            raise TypeError(
                'Pii base class cannot be instantiated directly. '
                'Please create a specific Pii subclass (e.g., PiiEmail, PiiSsn) '
                "and override its '_level' class attribute if needed."
            )

        # Get encryption singleton
        pii_encryption = PiiEncryption.get_encryption()

        # Encrypt the value
        if is_encrypted and len(value) > 50:
            # Workaround until all existing notification tasks and retries have been drained, then remove the len check
            encrypted = value
        else:
            encrypted = pii_encryption.encrypt(value.encode()).decode()

        # Return a new string instance with the encrypted value
        # Using type: ignore since the return type is actually the subclass type, not just 'Pii'
        str_class = super().__new__(cls, encrypted)
        str_class._encrypted_value = encrypted
        return str_class

    def get_identifier_type(self) -> IdentifierType:
        raise NotImplementedError(f'Not implemented for Pii class: {self.__class__.__name__}')

    def get_encrypted_value(self) -> str:
        """Get the encrypted value of this Pii object.

        Returns:
            str: An encrypted string
        """
        return self._encrypted_value

    def get_pii(self) -> str:
        """Decrypt and return the PII value.

        Returns:
            str: The decrypted PII value
        """
        # Get encryption singleton
        pii_encryption = PiiEncryption.get_encryption()

        # Decrypt the value
        return pii_encryption.decrypt(self.encode()).decode()

    def __str__(self) -> str:
        """Return a string representation with redaction based on impact level.

        For LOW impact PII, returns the encrypted value.
        For MODERATE and HIGH impact PII, returns "redacted" followed by the class name.

        Returns:
            str: String representation of the PII data
        """
        if self.level == PiiLevel.LOW:
            return super().__str__()
        else:
            # Use the class name as the suffix
            class_name = self.__class__.__name__
            return f'redacted {class_name}'

    def __repr__(self) -> str:
        """Return a string representation suitable for debugging.

        This method returns the same value as __str__ to ensure no accidental
        exposure of PII in debug logs or console output.

        Returns:
            str: Same as __str__ to avoid accidental PII exposure
        """
        return self.__str__()
