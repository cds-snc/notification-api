# V2 Query and Pagination Pattern

- Normalize query params from `request.args.to_dict(flat=False)` before schema validation.
- Flatten single-value fields (for example `older_than`, `reference`, `include_jobs`) from list to scalar.
- Validate normalized params with V2 schema.
- Use cursor-style pagination in V2 (`older_than`) instead of internal page/total pagination.
- Return `_links.current` and optional `_links.next` based on last item ID.

## Snippets

### Normalize + validate query args

```python
_data = request.args.to_dict(flat=False)
if "older_than" in _data:
    _data["older_than"] = _data["older_than"][0]
if "reference" in _data:
    _data["reference"] = _data["reference"][0]
if "include_jobs" in _data:
    _data["include_jobs"] = _data["include_jobs"][0]

data = validate(_data, get_<entity>_request)
```

### Build V2 cursor links

```python
_links = {"current": url_for(".get_<entities>", _external=True, **data)}
if len(items):
    next_query = dict(data, older_than=items[-1].id)
    _links["next"] = url_for(".get_<entities>", _external=True, **next_query)
```
