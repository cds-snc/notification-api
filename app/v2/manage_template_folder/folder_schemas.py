from app.schema_validation.definitions import uuid

get_template_folder_by_id_request = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "GET/PATCH/DELETE schema for a single manage template folder",
    "type": "object",
    "properties": {"id": uuid},
    "required": ["id"],
}
