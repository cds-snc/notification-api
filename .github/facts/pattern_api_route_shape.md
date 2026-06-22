# API Route Shape

- Use Blueprint with explicit url_prefix.
- Register errors on the blueprint via register_errors(...).
- For write operations, parse request JSON and validate payload with schema validation.
- Return jsonify payloads with explicit status codes.
- Use UUID path parameter conventions consistent with existing routes.
- Keep route naming and placement aligned with module conventions.

## Snippets

### Internal API route skeleton (app/<module>/rest.py)

```python
from flask import Blueprint, jsonify, request

from app.errors import register_errors
from app.schema_validation import validate

<module>_blueprint = Blueprint("<module>", __name__, url_prefix="/service/<uuid:service_id>/<module-kebab>")
register_errors(<module>_blueprint)


@<module>_blueprint.route("", methods=["POST"])
def create_<entity>(service_id):
	data = request.get_json()
	validate(data, post_create_<entity>_schema)
	item = <Model>(**data, service_id=service_id)
	dao_create_<entity>(item)
	return jsonify(item.serialize()), 201
```

### V2 route skeleton (app/v2/<module>/post_<entity>.py)

```python
from flask import jsonify, request

from app.schema_validation import validate
from app.v2.<module> import v2_<module>_blueprint


@v2_<module>_blueprint.route("", methods=["POST"])
def post_<entity>():
	data = validate(request.get_json() or {}, post_<entity>_request)
	item = create_<entity>(authenticated_service.id, data)
	return jsonify(item.serialize()), 201
```