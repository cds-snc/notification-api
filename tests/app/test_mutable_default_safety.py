import inspect
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest

from app.models import User
from tests.app.db import create_user


class TestSaveUserAttributeDefaultUpdateDictNotSharedBetweenCalls:
    """Testing thread safety related to mutable defaults

    One test that demonstrates how `param=None` defaults provides cross-call / shared-state safety across threads attempting to mutate parameters.
    One test that demonstrates how `param={}` mutable defaults result in a lack of thread safety
    """

    def test_save_user_attribute_default_update_dict_not_shared_between_calls(self, client, notify_db, notify_db_session):
        from app.dao.users_dao import save_user_attribute

        # Create 20 users
        users = [create_user(email=f"user{i}@example.com") for i in range(20)]

        # Capture the update_dict parameter
        shared_default = inspect.signature(save_user_attribute).parameters["update_dict"].default

        def worker(i):
            with client.application.app_context():
                with pytest.raises(AttributeError):
                    # Attempt mutation
                    shared_default.update({"name": "LEAKED"})
                    save_user_attribute(users[i])

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(worker, range(len(users))))

    @pytest.mark.skip(reason="Demonstrates the lack of thread safety when using mutable default dicts")
    def test_save_user_attribute_default_update_dict_not_shared_between_calls_not_safe(
        self, client, notify_db, notify_db_session
    ):
        """First run update the method app/dao/users_dao.py – save_user_attribute (line 26)
        ```
            def save_user_attribute(usr: User, update_dict={}):
                if "blocked" in update_dict and update_dict["blocked"]:
                    update_dict.update({"current_session_id": "00000000-0000-0000-0000-000000000000"})
        ```
        """
        from app.dao.users_dao import save_user_attribute

        # Create 20 users
        users = [create_user(email=f"user{i}@example.com") for i in range(20)]

        # Capture the update_dict parameter
        shared_default = inspect.signature(save_user_attribute).parameters["update_dict"].default

        def worker(i):
            with client.application.app_context():
                if i % 2 == 0:
                    # Access and mutate the shared default of update_dict
                    shared_default.update({"name": f"LEAKED{i}"})
                    save_user_attribute(
                        users[i],
                        {
                            "name": f"User{i}",
                            "blocked": i % 2 == 0,
                        },
                    )
                else:
                    save_user_attribute(users[i])

        # Execute across threads
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(worker, range(len(users))))

        notify_db_session.session.expire_all()

        # Ensure each user received only its own update
        for i, user in enumerate(users):
            updated = notify_db_session.session.query(User).populate_existing().filter_by(id=user.id).one()
            # Breakpoint on the `if` below, inspect the list of users, every third user in the list
            # will have a "LEAKED{i}" value that does not correspond to its index in the
            # list because each thread mutates the value of update_dict, simulating what could happen
            # in a multi-threaded environment.
            if i % 2 == 0:
                assert updated.name == f"User{i}"
                assert updated.blocked == (i % 2 == 0)
                assert updated.current_session_id == UUID("00000000-0000-0000-0000-000000000000")
            else:
                assert updated.name == f"LEAKED{i}", f"Saved username should be LEAKED{i} but got {updated.name}"
                assert updated.current_session_id != UUID("00000000-0000-0000-0000-000000000000")


class TestErrorConstructorParamsNotSharedBetweenCalls:
    def test_cannot_remove_user_error_thread_safe(self):
        from app.errors import CannotRemoveUserError

        def make_error(i):
            e = CannotRemoveUserError()
            e.fields.append(i)
            return e.fields

        with ThreadPoolExecutor(max_workers=20) as pool:
            results = list(pool.map(make_error, range(100)))

        # Each thread should own an isolated list
        for i, fields in enumerate(results):
            assert fields == [i]

    @pytest.mark.skip("Demonstrates the lack of thread safety when using mutable default lists")
    def test_cannot_remove_user_error_not_thread_safe(self):
        """First modify app/errors::CannotRemoveUserError L44

        ```
        def __init__(self, fields=[], message=None, status_code=400):
            # Call parent class __init__ with message and status_code
            super().__init__(message=message if message else self.message, status_code=status_code)
            self.fields = fields
        ```
        """
        from app.errors import CannotRemoveUserError

        def make_error(i):
            e = CannotRemoveUserError()
            e.fields.append(i)
            return e.fields

        with ThreadPoolExecutor(max_workers=20) as pool:
            results = list(pool.map(make_error, range(100)))

        # Each thread should own an isolated list, but it does not
        # Breakpoint on the assert, and check id(results[0])..1,2,3 etc
        # Notice that object ID remains the same across calls.
        for i, fields in enumerate(results):
            assert fields == [i]
