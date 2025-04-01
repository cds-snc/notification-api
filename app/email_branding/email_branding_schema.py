from app.models import BRANDING_TYPES
from app.schema_validation.definitions import uuid

post_create_email_branding_schema = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "POST schema for getting email_branding",
    "type": "object",
    "properties": {
        "colour": {"type": ["string", "null"]},
        "name": {"type": "string"},
        "text": {"type": ["string", "null"]},
        "logo": {"type": ["string", "null"]},
        "brand_type": {"enum": BRANDING_TYPES},
        "alt_text_en": {"type": "string"},
        "alt_text_fr": {"type": "string"},
        "created_by_id": uuid,
        "updated_by_id": uuid,
    },
    "required": ["name", "alt_text_en", "alt_text_fr", "created_by_id"],
}

post_update_email_branding_schema = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "POST schema for getting email_branding",
    "type": "object",
    "properties": {
        "colour": {"type": ["string", "null"]},
        "name": {"type": ["string", "null"]},
        "text": {"type": ["string", "null"]},
        "logo": {"type": ["string", "null"]},
        "brand_type": {"enum": BRANDING_TYPES},
        "alt_text_en": {"type": "string"},
        "alt_text_fr": {"type": "string"},
        "created_by_id": uuid,
        "updated_by_id": uuid,
    },
    "required": ["updated_by_id"],
}
