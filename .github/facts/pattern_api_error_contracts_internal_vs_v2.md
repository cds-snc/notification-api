# API Error Contracts: Internal vs V2

- Internal API (`app/errors.py`) typically responds with `{"result": "error", "message": "..."}`.
- V2 API (`app/v2/errors.py`) responds with `{"status_code": <int>, "errors": [{"error": "...", "message": "..."}]}`.
- `register_errors(...)` must match stack: internal routes use `app.errors.register_errors`, V2 routes use `app.v2.errors.register_errors`.
- `NoResultFound` maps to 404 in both stacks, but payload shape differs.

## Snippets

### Internal API error shape

```python
return jsonify(result="error", message="No result found"), 404
```

### V2 API error shape

```python
return (
    jsonify(
        status_code=404,
        errors=[{"error": "NoResultFound", "message": "No result found"}],
    ),
    404,
)
```
