from app.model.mobile_app import MobileApp
from app.schemas import BaseSchema
from flask_marshmallow.fields import fields


class MobileAppSchema(BaseSchema):
    class Meta:
        model = MobileApp

    app_name = fields.String(required=True)
    app_sid = fields.String(required=True)
