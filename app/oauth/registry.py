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
    client_kwargs={'scope': 'user'}
)
