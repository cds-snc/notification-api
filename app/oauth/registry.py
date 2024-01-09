from authlib.integrations.flask_client import OAuth

# .register() will automatically read GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET from app configuration
# as described here: https://docs.authlib.org/en/latest/client/flask.html#configuration

oauth_registry = OAuth()
oauth_registry.register(  # nosec
    name='github',
    access_token_url='https://github.com/login/oauth/access_token',
    access_token_params=None,
    authorize_url='https://github.com/login/oauth/authorize',
    authorize_params=None,
    api_base_url='https://api.github.com/',
    client_kwargs={'scope': 'read:user, user:email, read:org'},
)

# Reads all configuration from .well-known endpointed defined in VA_SSO_SERVER_METADATA_URL config
oauth_registry.register(
    name='va_sso', client_kwargs={'scope': 'openid', 'token_endpoint_auth_method': 'client_secret_post'}
)
