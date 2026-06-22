# API Validation Contract

- Use `validate(payload, schema)` from `app.schema_validation` for request validation.
- Validation failures produce a 400 response envelope with `status_code` and `errors`.
- Error entries use `{"error": "ValidationError", "message": "..."}` shape.
- Deduplicate repeated validation errors before returning.
- If `personalisation` is present, validation may include personalisation/file decoding checks.

## Snippets

### Validate incoming body

```python
data = request.get_json() or {}
validated = validate(data, post_<entity>_request)
```

### Expected validation error envelope

```json
{
  "status_code": 400,
  "errors": [
    {"error": "ValidationError", "message": "template_id is a required property"}
  ]
}
```
