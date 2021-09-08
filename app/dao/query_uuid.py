from app import db
from app.models import Service, User, Template, Notification


def query_uuid(uuid):
    service = Service.query.filter(Service.id.ilike(f"{uuid}")).one_or_none()
    if service:
        return {"type": "service", "service_id": uuid}

    notification = Notification.query.filter(Notification.id.ilike(f"{uuid}")).one_or_none()
    if notification:
        return {"type": "notification", "notification_id": uuid, "service_id": notification.service_id}

    user = User.query.filter(User.id.ilike(f"{uuid}")).one_or_none()
    if user:
        return {"type": "user", "user_id": uuid}

    template = Template.query.filter(Template.id.ilike(f"{uuid}")).one_or_none()
    if template:
        return {"type": "template", "template_id": uuid, "service_id": template.service_id}

    return {"type": "not found"}
