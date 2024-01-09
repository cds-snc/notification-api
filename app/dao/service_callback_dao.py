from app import db
from app.models import ServiceCallback
from notifications_utils.statsd_decorators import statsd
from sqlalchemy import select


@statsd(namespace='dao')
def dao_get_callback_include_payload_status(
    service_id,
    service_callback_type,
) -> bool:
    """Return whether the ServiceCallback has indicated that the provider should include the payload"""
    include_provider_payload = False

    stmt = select(ServiceCallback).where(
        ServiceCallback.service_id == service_id,
        ServiceCallback.callback_type == service_callback_type,
        ServiceCallback.include_provider_payload.is_(True),
    )

    row = db.session.scalars(stmt).first()

    if row is not None:
        include_provider_payload = row.include_provider_payload

    return include_provider_payload
