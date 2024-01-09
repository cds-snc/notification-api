from app.dao.provider_rates_dao import create_provider_rates
from app.models import ProviderRates
from datetime import datetime
from decimal import Decimal


def test_create_provider_rates(notify_api, mmg_provider):
    now = datetime.now()
    rate = Decimal('1.00000')

    create_provider_rates(mmg_provider.identifier, now, rate)
    assert ProviderRates.query.count() == 1
    assert ProviderRates.query.first().rate == rate
    assert ProviderRates.query.first().valid_from == now
