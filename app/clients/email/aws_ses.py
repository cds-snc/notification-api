import re
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from time import monotonic

import boto3
import botocore
from flask import current_app
from notifications_utils.recipients import InvalidEmailError
from notifications_utils.statsd_decorators import statsd

from app.clients.email import EmailClient, EmailClientException
from app.inline_images import get_inline_image_mime_type


class AwsSesClientException(EmailClientException):
    pass


class AwsSesClient(EmailClient):
    """
    Amazon SES email client.
    """

    def init_app(self, region, statsd_client, *args, **kwargs):
        self._client = boto3.client("ses", region_name=region)
        super(AwsSesClient, self).__init__(*args, **kwargs)
        self.name = "ses"
        self.statsd_client = statsd_client

    def get_name(self):
        return self.name

    @statsd(namespace="clients.ses")
    def send_email(
        self,
        source,
        to_addresses,
        subject,
        body,
        html_body="",
        reply_to_address=None,
        attachments=None,
        extra_headers=None,
        inline_images=None,
    ):
        def create_mime_base(attachments, html):
            msg_type = "mixed" if attachments or (not attachments and not html) else "alternative"
            ret = MIMEMultipart(msg_type)
            ret["Subject"] = subject
            ret["From"] = source
            ret["To"] = ",".join([punycode_encode_email(addr) for addr in to_addresses])
            if reply_to_addresses:
                ret.add_header(
                    "reply-to",
                    ",".join([punycode_encode_email(addr) for addr in reply_to_addresses]),
                )
            for header_name, header_value in (extra_headers or {}).items():
                ret[header_name] = header_value
            return ret

        def attach_html(m, content):
            if content:
                parts = MIMEText(content, "html")
                if inline_images:
                    related = MIMEMultipart("related")
                    related.attach(parts)
                    for image in inline_images:
                        content_id = image["content_id"]
                        if not isinstance(content_id, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.@-]{0,127}", content_id):
                            raise ValueError("Invalid inline image content ID")
                        mime_type = get_inline_image_mime_type(image["data"])
                        if mime_type != image["mime_type"]:
                            raise ValueError("Inline image content does not match its MIME type")
                        part = MIMEImage(image["data"], _subtype=mime_type.split("/")[1])
                        part.add_header("Content-ID", f"<{content_id}>")
                        part.add_header("Content-Disposition", "inline", filename=image["name"])
                        related.attach(part)
                    parts = related
                m.attach(parts)

        attachments = attachments or []
        if isinstance(to_addresses, str):
            to_addresses = [to_addresses]

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
        #
        # Inline images wrap the HTML part in multipart/related.

        try:
            if inline_images:
                if not current_app.config["FF_ENABLE_INLINE_IMAGES"]:
                    raise ValueError("Inline images are not enabled")
                if not html_body:
                    raise ValueError("Inline images require an HTML email body")
                content_ids = [image["content_id"] for image in inline_images]
                if len(set(content_ids)) != len(content_ids):
                    raise ValueError("Inline image content IDs must be unique")
            msg = create_mime_base(attachments, html_body)
            txt_part = MIMEText(body, "plain")

            if attachments and html_body:
                msg_alternative = MIMEMultipart("alternative")
                msg_alternative.attach(txt_part)
                attach_html(msg_alternative, html_body)
                msg.attach(msg_alternative)
            else:
                msg.attach(txt_part)
                attach_html(msg, html_body)

            for attachment in attachments:
                # See https://docs.aws.amazon.com/ses/latest/DeveloperGuide/send-email-raw.html#send-email-raw-mime
                attachment_part = MIMEApplication(attachment["data"])
                if attachment.get("mime_type"):
                    attachment_part.add_header("Content-Type", attachment["mime_type"], name=attachment["name"])
                attachment_part.add_header("Content-Disposition", "attachment", filename=attachment["name"])
                msg.attach(attachment_part)

            start_time = monotonic()
            response = self._client.send_raw_email(Source=source, RawMessage={"Data": msg.as_string()})
        except botocore.exceptions.ClientError as e:
            self.statsd_client.incr("clients.ses.error")

            # http://docs.aws.amazon.com/ses/latest/DeveloperGuide/api-error-codes.html
            if e.response["Error"]["Code"] == "InvalidParameterValue":
                raise InvalidEmailError(f'message: "{e.response["Error"]["Message"]}"')
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
            return response["MessageId"]


def punycode_encode_email(email_address):
    # only the hostname should ever be punycode encoded.
    local, hostname = email_address.split("@")
    return "{}@{}".format(local, hostname.encode("idna").decode("ascii"))
