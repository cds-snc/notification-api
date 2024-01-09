# https://flask-sqlalchemy.palletsprojects.com/en/3.0.x/api/
from flask_sqlalchemy import SQLAlchemy as _SQLAlchemy


class SQLAlchemy(_SQLAlchemy):
    """Subclass SQLAlchemy in order to override create_engine options."""

    def apply_driver_hacks(
        self,
        app,
        info,
        options,
    ):
        super().apply_driver_hacks(app, info, options)
        if 'connect_args' not in options:
            options['connect_args'] = {}
        options['connect_args']['options'] = '-c statement_timeout={}'.format(
            int(app.config['SQLALCHEMY_STATEMENT_TIMEOUT']) * 1000
        )


db = SQLAlchemy()
