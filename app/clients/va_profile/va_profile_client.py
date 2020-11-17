from flask import current_app


class VAProfileClient:
    #
    # def __init__(
    #         self
    # ):
    #     pass

    def get_email(self, va_profile_id):
        current_app.logger.info("Querying VA Profile with ID " + va_profile_id)

        # connect to VAProfile

        # build the request

        # send GET request

        # parse the response

        # extract the email address

        return "test@test.com"

