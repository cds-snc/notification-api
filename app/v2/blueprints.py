from flask_smorest import Blueprint


class PaginationBlueprint(Blueprint):
    """A simple extension of the smorest blueprint so that we can override smorests default pagination parameters.

    We do this because of the order in which blueprints and @pagination decorators are evaluated.
    1. Blueprints are instantiated / evaluated in the order they are imported
    2. @pagination decorators are then evaluated, which configure themselves with the blueprints pagination params
    3. Then the app config is finally loaded
    4. Blueprints are registered with the app

    Since the blueprints are evaluated first, and DEFAULT_PAGINATION_PARAMETERS is immutable once set, then by the time
    the app config is available to inject API_PAGE_SIZE into the blueprint, it's already too late. There's probably a good
    reason why route configuration occurs before the blueprints are registered with the application but it's certainly a
    PITA.
    Reference: https://flask-smorest.readthedocs.io/en/latest/pagination.html#pagination-parameters
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.DEFAULT_PAGINATION_PARAMETERS = {
            "page": 1,
            "page_size": 250,  # API_PAGE_SIZE
            "max_page_size": 250,  # API_PAGE_SIZE
        }
