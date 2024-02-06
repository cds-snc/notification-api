from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import delete

from app.dao.provider_rates_dao import create_provider_rates
from app.models import ProviderRates


def test_create_provider_rates(notify_db_session, sample_provider):
    now = datetime.now()
    rate = Decimal('1.00000')

    provider = sample_provider(str(uuid4()))
    provider_rates = create_provider_rates(provider.identifier, now, rate)

    try:
        assert notify_db_session.session.get(ProviderRates, provider_rates.id) is not None
        assert provider_rates.rate == rate
        assert provider_rates.valid_from == now
    finally:
        stmt = delete(ProviderRates).where(ProviderRates.id == provider_rates.id)
        notify_db_session.session.execute(stmt)
        notify_db_session.session.commit()
