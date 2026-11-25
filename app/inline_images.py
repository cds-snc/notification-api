from uuid import UUID

from flask import current_app

INLINE_IMAGE_MIME_TYPES = {"image/png", "image/jpeg"}


def is_service_allowed_inline_images(service_id: UUID | str) -> bool:
    return current_app.config["FF_ENABLE_INLINE_IMAGES"] and str(service_id) in current_app.config["INLINE_IMAGE_SERVICE_IDS"]


def get_inline_image_mime_type(data: bytes) -> str:
    import magic

    mime_type = magic.from_buffer(data, mime=True)
    if mime_type not in INLINE_IMAGE_MIME_TYPES:
        raise ValueError("Inline images must be PNG or JPEG files")
    return mime_type
