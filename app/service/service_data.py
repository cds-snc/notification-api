import json
from sqlalchemy.sql.expression import select
from types import SimpleNamespace
from typing import Union

from app.models import ApiKey, Service, User
from app.dao.dao_utils import get_reader_session


class ServiceDataException(Exception):
    """
    Custom exception class for handling specific errors related to the ServiceData class.

    Attributes:
        message (str): A custom message describing the error.

    Usage:
        raise ServiceDataException("Description...")
    """

    def __init__(
        self,
        message='Unable to create ServiceData object.',
        *args,
        **kwargs,
    ):
        super().__init__(message, *args, **kwargs)


class ServiceDataApiKey:
    """
    A class to encapsulate information related to an authenticated service's API key.

    This class serves as a data structure to hold the essential properties of an API key
    associated with an authenticated service. It includes a simplified representation of
    related service attributes (research mode, restricted, and active status).

    This is needed to deal with circular dependency and multilevel nesting in previously
    created SQLAlchemy model.

    Creating simple namespance to preseve dot notation used in calling functions.

    Attributes:
        created_at (datetime): The timestamp when the API key was created.
        created_by (User): The user who created the API key.
        created_by_id (str): The ID of the user who created the API key.
        expiry_date (datetime): The expiry date of the API key.
        revoked (bool): The property indicating if the key has been revoked or not
        id (str): The unique identifier of the API key.
        key_type (str): The type of the API key (e.g., "normal").
        name (str): The name of the API key.
        secret (str): The secret string associated with the API key.
        service (SimpleNamespace): A namespace containing the 'research_mode',
            'restricted', and 'active' attributes of the related service.
        service_id (str): The ID of the related service.
        updated_at (datetime): The timestamp when the API key was last updated.
    """

    def __init__(
        self,
        key: ApiKey,
    ) -> None:
        """
        Args:
            key (object): The object containing the necessary attributes for the API key.
        """
        self.created_at = key.created_at
        self.created_by_id = key.created_by_id
        self.expiry_date = key.expiry_date
        self.revoked = key.revoked
        self.id = key.id
        self.key_type = key.key_type
        self.name = key.name
        self.secret = key.secret

        _service = {
            'research_mode': key.service.research_mode,
            'restricted': key.service.restricted,
            'active': key.service.active,
        }
        self.service = SimpleNamespace(**_service)
        self.service_id = key.service_id
        self.updated_at = key.updated_at

    @property
    def created_by(self):
        """
        Returns the User object for the API Key creator
        """

        # Without the wrapper function the ORM object detaches in some cases
        def lazyload():
            with get_reader_session() as session:
                return session.execute(select(User).filter_by(id=self.created_by_id)).one()

        return lazyload

    def __eq__(
        self,
        other: 'ServiceDataApiKey',
    ) -> bool:
        """
        Determines equality between two instances of ServiceDataApiKey.

        Two instances of ServiceDataApiKey are considered equal if they have the same values for
        the following attributes:
            - id
            - name
            - key_type
            - created_by_id
            - service_id
            - secret

        Args:
            other (ServiceDataApiKey): The object to compare against.

        Returns:
            bool: True if the instances have the same values for the relevant attributes, False otherwise.
        """
        if isinstance(other, ServiceDataApiKey):
            return (
                self.id == other.id
                and self.key_type == other.key_type
                and self.name == other.name
                and self.service_id == other.service_id
                and self.created_by_id == other.created_by_id
                and self.secret == other.secret
            )
        return False


class ServiceData:
    """
    Represents the relevant information extracted from an SQLAlchemy query result.

    This class was created to allow for reading from multiple databases and to facilitate caching.
    By extracting only the necessary information from the query result, it ensures compatibility
    across different database connections and enables efficient serialization for caching purposes.
    The extraction of specific information rather than working with entire query results provides a
    more controlled and optimized way to handle the data.

    Attributes:
        active (bool): A flag indicating whether the service is active.
        permissions (list): A list of permissions associated with the service.
        api_keys (list): A list of API keys associated with the service.
        id (int): The unique identifier of the service.
        research_mode (bool): A flag indicating whether the service is in research mode.
        restricted (bool): A flag indicating whether the service is restricted.
        rate_limit (int): The rate limit applied to the service.
        service_sms_senders (list): A list of SMS senders associated with the service.
        message_limit (int): The message limit applied to the service.
        users (list): A list of users associated with the service.
        whitelist (list): A list of whitelisted entities for the service.

    Methods:
        <List the methods here, if applicable>
    """

    def __init__(
        self,
        result=None,
    ):
        self.active = None
        self.permissions = None
        self.api_keys = None
        self.id = None
        self.name = None
        self.research_mode = None
        self.restricted = None
        self.rate_limit = None
        self.service_sms_senders = None
        self.message_limit = None
        self.users = None
        self.whitelist = None
        if result is not None:
            try:
                self.extract(result)
            except Exception as err:
                raise ServiceDataException(err)

    def extract(
        self,
        result: Service,
    ) -> None:
        """
        Extracts the necessary data from an authenticated service ORM object.

        Args:
            result: The ORM object containing the data. WARNING it's not pure Service
                object, but Service augmented with api_keys

        Returns:
            None
        """
        self.active = result.active
        self.permissions = [p.permission for p in result.permissions]
        self.api_keys = [ServiceDataApiKey(key) for key in result.api_keys]
        self.id = result.id
        self.name = result.name
        self.research_mode = result.research_mode
        self.restricted = result.restricted
        self.rate_limit = result.rate_limit
        self.service_sms_senders = result.service_sms_senders
        self.message_limit = result.message_limit
        self.users = [u for u in result.users]
        self.whitelist = [w for w in result.whitelist]

    def serialize(self) -> str:
        """
        Serializes the object into a JSON string.
        This method might be used for caching, allowing the object to be easily stored and retrieved.

        Returns:
            str: A JSON string.
        """
        return json.dumps(self.__dict__)

    def has_permissions(
        self,
        permissions_to_check_for: Union[str, list[str], tuple[str]],
    ) -> bool:
        """
        Checks if the object has the specified permissions.

        Args:
            permissions_to_check_for (Union[str, list[str], tuple[str]]): A permission(s) to check for.

        Returns:
            bool: True if all specified permissions are present, False otherwise.
        """
        if not isinstance(permissions_to_check_for, list) and not isinstance(permissions_to_check_for, tuple):
            permissions_to_check_for = (permissions_to_check_for,)
        return frozenset(permissions_to_check_for).issubset(frozenset(self.permissions))

    @classmethod
    def deserialize(
        cls,
        json_string: str,
    ) -> 'ServiceData':
        """
        Creates a new instance of the class using a JSON string.
        This method might be used after retrieval from caching, allowing the object to be reconstructed.

        Args:
            json_string (str): A JSON string representing the object.

        Returns:
            ServiceData: A new instance of the class populated with the data from the JSON string.
        """
        result = cls()
        result.__dict__ = json.loads(json_string)
        return result
