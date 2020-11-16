from flask import current_app


class VAProfileClient:

    def get_email(self, va_profile_id):
        current_app.logger.info("Querying VA Profile with ID " + va_profile_id)
        return "test@test.com"