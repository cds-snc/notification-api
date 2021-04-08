import boto3
import botocore
from flask import current_app
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


class AwsSesClient(EmailClient):
    '''
    Amazon SES email client.
    '''

    def init_app(self, region, statsd_client, *args, **kwargs):
        self._client = boto3.client('ses', region_name=region)
        super(AwsSesClient, self).__init__(*args, **kwargs)
        self.name = 'ses'
        self.statsd_client = statsd_client

    def get_name(self):
        return self.name

    def send_email(
        self,
        source,
        to_addresses,
        subject,
        body,
        html_body='',
        reply_to_address=None,
        attachments=[],
    ):
        def create_mime_base(type):
            msg = MIMEMultipart(type)
            msg['Subject'] = subject
            msg['From'] = source
            msg['To'] = ",".join([punycode_encode_email(addr) for addr in to_addresses])
            if reply_to_addresses != []:
                msg.add_header('reply-to', ",".join([punycode_encode_email(addr) for addr in reply_to_addresses]))
            return msg

        if isinstance(to_addresses, str):
            to_addresses = [to_addresses]
        source = unidecode(source)
        reply_to_addresses = [reply_to_address] if reply_to_address else []

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

            start_time = monotonic()
            response = self._client.send_raw_email(
                Source=source,
                RawMessage={'Data': msg.as_string()}
            )
        except botocore.exceptions.ClientError as e:
            self.statsd_client.incr("clients.ses.error")

            # http://docs.aws.amazon.com/ses/latest/DeveloperGuide/api-error-codes.html
            if e.response['Error']['Code'] == 'InvalidParameterValue':
                raise InvalidEmailError('email: "{}" message: "{}"'.format(
                    to_addresses[0],
                    e.response['Error']['Message']
                ))
            else:
                self.statsd_client.incr("clients.ses.error")
                raise AwsSesClientException(str(e))
        except Exception as e:
            self.statsd_client.incr("clients.ses.error")
            raise AwsSesClientException(str(e))
        else:
            elapsed_time = monotonic() - start_time
            current_app.logger.info("AWS SES request finished in {}".format(elapsed_time))
            self.statsd_client.timing("clients.ses.request-time", elapsed_time)
            self.statsd_client.incr("clients.ses.success")
            return response['MessageId']


def punycode_encode_email(email_address):
    # only the hostname should ever be punycode encoded.
    local, hostname = email_address.split('@')
    return '{}@{}'.format(local, hostname.encode('idna').decode('utf-8'))
