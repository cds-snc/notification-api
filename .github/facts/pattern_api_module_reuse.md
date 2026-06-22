# Prefer Existing Modules

- Default behavior is to extend an existing domain module or client before creating a new one.
- In API work, check existing app domain folders first.
- In Admin work, check existing notify_client and main view modules first.
- Create a new module only when no existing domain fit is reasonable.
- When extending existing modules, match local naming, imports, and file conventions.

## Snippets

### Extend existing module

```python
# app/<module>/rest.py
@<module>_blueprint.route("/<uuid:<entity>_id>", methods=["POST"])
def update_<entity>(service_id, <entity>_id):
	data = request.get_json()
	validate(data, post_update_<entity>_schema)
	item = dao_get_<entity>_by_id_and_service_id(<entity>_id, service_id)
	for key, value in data.items():
		setattr(item, key, value)
	dao_update_<entity>(item)
	return jsonify(item.serialize()), 200
```

### New module scaffold (only if no fit)

```text
app/<module>/__init__.py
app/<module>/<module>_schema.py
app/dao/<module>_dao.py
app/<module>/rest.py
tests/app/<module>/test_rest.py
```