# API Blueprint Registration

- New API blueprints require import wiring in app bootstrap.
- Register with register_notify_blueprint(application, blueprint, auth_function, prefix_optional).
- Use auth function and prefix style that matches adjacent registrations.
- If only adding routes to an already-registered blueprint, do not touch registration.
- Keep registration order and grouping consistent with file conventions.

## Snippets

### Internal module registration

```python
# app/__init__.py -> register_blueprint()
from app.<module>.rest import <module>_blueprint
from app.authentication.auth import requires_admin_auth

register_notify_blueprint(application, <module>_blueprint, requires_admin_auth)
```

### V2 module registration

```python
# app/__init__.py -> register_v2_blueprints()
from app.v2.<module> import v2_<module>_blueprint
from app.v2.<module> import get_<entity>, post_<entity>
from app.authentication.auth import requires_auth

register_notify_blueprint(application, v2_<module>_blueprint, requires_auth)
```