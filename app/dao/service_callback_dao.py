from notifications_utils.statsd_decorators import statsd
from app.models import (ServiceCallback)


@statsd(namespace="dao")
def dao_get_callback_include_payload_status(service_id, service_callback_type) -> bool:
    """ Return whether the ServiceCallback has indicated that the provider should include the payload"""
    include_provider_payload = False

    row = ServiceCallback\
        .query.filter_by(service_id=service_id)\
        .filter_by(callback_type=service_callback_type) \
        .filter_by(include_provider_payload=True) \
        .first()

    if row is not None:
        include_provider_payload = row.include_provider_payload

    return include_provider_payload
