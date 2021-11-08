import boto3
import botocore
from time import monotonic
from notifications_utils.recipients import InvalidEmailError
from unidecode import unidecode

from app.clients import STATISTICS_DELIVERED, STATISTICS_FAILURE
from app.clients.email import (EmailClientException, EmailClient)
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

ses_response_map = {
    'Permanent': {
        "message": 'Hard bounced',
        "success": False,
        "notification_status": 'permanent-failure',
        "notification_statistics_status": STATISTICS_FAILURE
    },
    'Temporary': {
        "message": 'Soft bounced',
        "success": False,
        "notification_status": 'temporary-failure',
        "notification_statistics_status": STATISTICS_FAILURE
    },
    'Delivery': {
        "message": 'Delivered',
        "success": True,
        "notification_status": 'delivered',
        "notification_statistics_status": STATISTICS_DELIVERED
    },
    'Complaint': {
        "message": 'Complaint',
        "success": True,
        "notification_status": 'delivered',
        "notification_statistics_status": STATISTICS_DELIVERED
    }
}


def get_aws_responses(status):
    return ses_response_map[status]


class AwsSesClientException(EmailClientException):
    pass


class AwsSesClientThrottlingSendRateException(AwsSesClientException):
    pass


class AwsSesClient(EmailClient):
    '''
    Amazon SES email client.
    '''

    def init_app(self, region, logger, statsd_client, email_from_domain=None, email_from_user=None,
                 default_reply_to=None, configuration_set=None, endpoint_url=None, *args, **kwargs):
        self._client = boto3.client('ses', region_name=region, endpoint_url=endpoint_url)
        super(AwsSesClient, self).__init__(*args, **kwargs)
        self.name = 'ses'
        self.statsd_client = statsd_client
        self._email_from_domain = email_from_domain
        self._email_from_user = email_from_user
        self._default_reply_to_address = default_reply_to
        self._configuration_set = configuration_set
        self.logger = logger

    def get_name(self):
        return self.name

    @property
    def email_from_domain(self):
        return self._email_from_domain

    @property
    def email_from_user(self):
        return self._email_from_user

    def send_email(
        self,
        source,
        to_addresses,
        subject,
        body,
        html_body='',
        reply_to_address=None,
        attachments=None,
    ):
        def create_mime_base(type):
            msg = MIMEMultipart(type)
            msg['Subject'] = subject
            msg['From'] = source
            msg['To'] = ",".join([punycode_encode_email(addr) for addr in to_addresses])
            if reply_to_address:
                msg.add_header('reply-to', punycode_encode_email(reply_to_address))
            return msg

        attachments = attachments or []
        if isinstance(to_addresses, str):
            to_addresses = [to_addresses]
        source = unidecode(source)
        reply_to_address = reply_to_address if reply_to_address else self._default_reply_to_address

        kwargs = {'ConfigurationSetName': self._configuration_set} if self._configuration_set else {}

        # - If sending a TXT email without attachments:
        #   => Multipart mixed
        #
        # - If sending a TXT + HTML email without attachments:
        #   => Multipart alternative
        #
        # - If sending a TXT + HTML email with attachments
        # =>  Multipart Mixed (enclosing)
        #       - Multipart alternative
        #         - TXT
        #         - HTML
        #       - Attachment(s)

        start_time = monotonic()
        try:
            txt_part = MIMEText(body, 'plain')
            if html_body:
                html_part = MIMEText(html_body, 'html')

            if not attachments:
                multipart_content_subtype = 'alternative' if html_body else 'mixed'
                msg = create_mime_base(multipart_content_subtype)
                msg.attach(txt_part)
                if html_body:
                    msg.attach(html_part)
            else:
                msg = create_mime_base('mixed')
                if html_body:
                    msg_alternative = MIMEMultipart('alternative')
                    msg_alternative.attach(txt_part)
                    msg_alternative.attach(html_part)

                    msg.attach(msg_alternative)
                else:
                    msg.attach(txt_part)

                for attachment in attachments:
                    attachment_part = MIMEApplication(attachment["data"])
                    attachment_part.add_header('Content-Disposition', 'attachment', filename=attachment["name"])
                    msg.attach(attachment_part)

            response = self._client.send_raw_email(
                Source=source,
                RawMessage={'Data': msg.as_string()},
                **kwargs
            )
        except botocore.exceptions.ClientError as e:
            self._check_error_code(e, to_addresses)
        except Exception as e:
            self.statsd_client.incr("clients.ses.error")
            raise AwsSesClientException(str(e))
        else:
            self.statsd_client.incr("clients.ses.success")
            return response['MessageId']
        finally:
            elapsed_time = monotonic() - start_time
            self.logger.info("AWS SES request finished in {}".format(elapsed_time))
            self.statsd_client.timing("clients.ses.request-time", elapsed_time)

    def _check_error_code(self, e, to_addresses):
        # http://docs.aws.amazon.com/ses/latest/DeveloperGuide/api-error-codes.html
        if e.response['Error']['Code'] == 'InvalidParameterValue':
            self.statsd_client.incr("clients.ses.error.invalid-email")
            raise InvalidEmailError('message: "{}"'.format(e.response['Error']['Message']))
        elif (
                e.response['Error']['Code'] == 'Throttling'
                and e.response['Error']['Message'] == 'Maximum sending rate exceeded.'
        ):
            self.statsd_client.incr("clients.ses.error.throttling")
            raise AwsSesClientThrottlingSendRateException(str(e))
        else:
            self.statsd_client.incr("clients.ses.error")
            raise AwsSesClientException(str(e))


def punycode_encode_email(email_address):
    # AWS requires emails to be punycode encoded
    # https://docs.aws.amazon.com/ses/latest/DeveloperGuide/send-email-raw.html
    # only the hostname should ever be punycode encoded.
    local, hostname = email_address.split('@')
    return '{}@{}'.format(local, hostname.encode('idna').decode('ascii'))
