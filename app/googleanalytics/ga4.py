"""
Google Analytics 4
"""

import os

from flask import current_app, Blueprint, request, send_file
from jsonschema import FormatChecker, ValidationError
from jsonschema.validators import Draft202012Validator

from app.googleanalytics.ga4_schemas import ga4_request_schema
from app.celery.process_ga4_measurement_tasks import post_to_ga4

ga4_blueprint = Blueprint('ga4', __name__, url_prefix='/ga4')

ga4_request_validator = Draft202012Validator(ga4_request_schema, format_checker=FormatChecker(['uuid']))

GA4_PIXEL_TRACKING_IMAGE_PATH = f'{os.getcwd()}/images/ga4_pixel_tracking.png'


@ga4_blueprint.route('/open-email-tracking', methods=['GET'])
def get_ga4():
    """
    This route is used for pixel tracking.  It is exercised when a veteran opens an e-mail.
    The route returns a pixel image to avoid a broken icon image in notification emails.
    """
    # https://flask.palletsprojects.com/en/3.0.x/api/#flask.Request.args
    url_parameters_dict = request.args.to_dict()
    current_app.logger.debug('GA4 url params: %s', url_parameters_dict)

    # This could raise ValidationError.
    ga4_request_validator.validate(url_parameters_dict)

    template_name = url_parameters_dict['campaign']
    template_id = url_parameters_dict['campaign_id']
    name = url_parameters_dict['name']
    source = url_parameters_dict['source']
    medium = url_parameters_dict['medium']
    service_name, service_id, notification_id = url_parameters_dict['content'].split('/')

    current_app.logger.info(
        'GA4: post_to_ga4: template_name: %s, template_id: %s, service_name: %s, service_id: %s, notification_id: %s',
        template_name,
        template_id,
        service_name,
        service_id,
        notification_id,
    )
    post_to_ga4.delay(
        notification_id,
        template_name,
        template_id,
        service_id,
        service_name,
        name=name,
        source=source,
        medium=medium,
    )

    return send_file(GA4_PIXEL_TRACKING_IMAGE_PATH, mimetype='image/png')


@ga4_blueprint.errorhandler(ValidationError)
def ga4_schema_validation_error(error):
    current_app.logger.exception('GA4 ValidationError: %s', error.message)

    return {
        'errors': [
            {
                'error': 'ValidationError',
                'message': error.message,
            }
        ]
    }, 400
