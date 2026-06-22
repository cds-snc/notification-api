# DAO Transaction Pattern

- Mutating DAO functions use the transactional decorator.
- Mutations use db session add, update, or delete operations.
- Commit and rollback behavior is delegated to decorator flow.
- Keep guard clauses and domain validation near mutation logic.
- Follow existing DAO naming conventions for get, fetch, create, update, and archive operations.

## Snippets

### Query patterns (no @transactional)

```python
def dao_get_<entity>_by_id(<entity>_id):
	return <Model>.query.filter_by(id=<entity>_id).one()


def dao_fetch_<entities>_for_service(service_id):
	return <Model>.query.filter_by(service_id=service_id).all()
```

### Mutation patterns (@transactional)

```python
from app import db
from app.dao.dao_utils import transactional


@transactional
def dao_create_<entity>(item):
	db.session.add(item)


@transactional
def dao_archive_<entity>(item):
	item.archived = True
	db.session.add(item)
```