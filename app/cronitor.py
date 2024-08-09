import requests
from flask import current_app
from functools import wraps


def cronitor(task_name):
    # check if task_name is in config
    def decorator(func):
        def ping_cronitor(command):
            if not current_app.config['CRONITOR_ENABLED']:
                return

            task_slug = current_app.config['CRONITOR_KEYS'].get(task_name)
            if not task_slug:
                current_app.logger.error('Cronitor enabled, but task_name %s not found in environment.', task_name)
                return

            if command not in {'run', 'complete', 'fail'}:
                raise ValueError('command {} not a valid cronitor command'.format(command))

            try:
                resp = requests.get(
                    f'https://cronitor.link/{task_slug}/{command}',
                    # cronitor limits msg to 1000 characters
                    params={
                        'host': current_app.config['API_HOST_NAME'],
                    },
                    timeout=(3.05, 1),
                )
                resp.raise_for_status()
            except requests.RequestException:
                current_app.logger.exception('Cronitor API failed for task %s.', task_name)

        @wraps(func)
        def inner_decorator(
            *args,
            **kwargs,
        ):
            ping_cronitor('run')
            try:
                ret = func(*args, **kwargs)
                status = 'complete'
                return ret
            except Exception:
                status = 'fail'
                raise
            finally:
                ping_cronitor(status)

        return inner_decorator

    return decorator
