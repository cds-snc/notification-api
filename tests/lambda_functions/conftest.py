from random import randint
from typing import Optional

import pytest
from sqlalchemy import delete

from app.models import VAProfileLocalCache


@pytest.fixture
def sample_va_profile_local_cache(notify_db_session):
    created_va_profile_local_cache_ids = []

    def _sample_va_profile_local_cache(
        source_datetime: str,
        allowed: bool = True,
        va_profile_id: Optional[int] = None,
        communication_item_id: int = 5,
        communication_channel_id: int = 1,
    ):
        """
        The combination of va_profile_id, communication_item_id, and communication_channel_id must be unique.
        """

        va_profile_local_cache = VAProfileLocalCache(
            allowed=allowed,
            va_profile_id=(va_profile_id if (va_profile_id is not None) else randint(1000, 100000)),
            communication_item_id=communication_item_id,
            communication_channel_id=communication_channel_id,
            source_datetime=source_datetime,
        )

        notify_db_session.session.add(va_profile_local_cache)
        notify_db_session.session.commit()
        created_va_profile_local_cache_ids.append(va_profile_local_cache.id)
        return va_profile_local_cache

    yield _sample_va_profile_local_cache

    # Teardown
    stmt = delete(VAProfileLocalCache).where(VAProfileLocalCache.id.in_(created_va_profile_local_cache_ids))
    notify_db_session.session.execute(stmt)
    notify_db_session.session.commit()
