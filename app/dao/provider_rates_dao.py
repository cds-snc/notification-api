from app import db
from app.dao.dao_utils import transactional
from app.models import ProviderRates, ProviderDetails
from sqlalchemy import select


@transactional
def create_provider_rates(
    provider_identifier,
    valid_from,
    rate,
):
    """
    #2249 Caching the ProviderDetails select query in this function is unnecessary.  This
    function is only called via app/commands.py, which isn't used.
    """

    stmt = select(ProviderDetails).where(ProviderDetails.identifier == provider_identifier)
    provider = db.session.scalars(stmt).one()

    provider_rates = ProviderRates(provider_id=provider.id, valid_from=valid_from, rate=rate)
    db.session.add(provider_rates)
    return provider_rates
