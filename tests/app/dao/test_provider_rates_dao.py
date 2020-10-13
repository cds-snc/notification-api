from datetime import datetime
from decimal import Decimal
from app.dao.provider_rates_dao import create_provider_rates
from app.models import ProviderRates, ProviderDetails


def test_create_provider_rates(notify_db, notify_db_session, ses_provider):
    now = datetime.now()
    rate = Decimal("1.00000")

    provider = ProviderDetails.query.filter_by(identifier=ses_provider.identifier).one()

    create_provider_rates(ses_provider.identifier, now, rate)
    assert ProviderRates.query.count() == 1
    assert ProviderRates.query.first().rate == rate
    assert ProviderRates.query.first().valid_from == now
    assert ProviderRates.query.first().provider_id == provider.id
