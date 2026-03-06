from time import monotonic

import phonenumbers
from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client as TwilioClient

from app.clients.sms import RcsClient


class TwilioRcsClient(RcsClient):
    """
    Twilio RCS client for sending RCS messages.
    Uses the Twilio Messages API with a messaging service configured for RCS.
    """

    def init_app(self, current_app, statsd_client, *args, **kwargs):
        self._client = TwilioClient(
            current_app.config["TWILIO_ACCOUNT_SID"],
            current_app.config["TWILIO_AUTH_TOKEN"],
        )
        self._messaging_service_sid = current_app.config["TWILIO_RCS_MESSAGING_SERVICE_SID"]
        super(TwilioRcsClient, self).__init__(*args, **kwargs)
        self.current_app = current_app
        self.name = "twilio"
        self.statsd_client = statsd_client

    def get_name(self):
        return self.name

    def send_rcs(self, to, content, sender=None, template_id=None, service_id=None):
        matched = False

        for match in phonenumbers.PhoneNumberMatcher(to, "US"):
            matched = True
            to = phonenumbers.format_number(match.number, phonenumbers.PhoneNumberFormat.E164)

            try:
                start_time = monotonic()
                message = self._client.messages.create(
                    to=to,
                    messaging_service_sid=self._messaging_service_sid,
                    body=content,
                )
            except TwilioRestException:
                self.statsd_client.incr("clients.twilio-rcs.error")
                raise
            except Exception:
                self.statsd_client.incr("clients.twilio-rcs.error")
                raise
            finally:
                elapsed_time = monotonic() - start_time
                self.current_app.logger.info("Twilio RCS request finished in {}".format(elapsed_time))
                self.statsd_client.timing("clients.twilio-rcs.request-time", elapsed_time)
                self.statsd_client.incr("clients.twilio-rcs.success")
            return message.sid

        if not matched:
            self.statsd_client.incr("clients.twilio-rcs.error")
            self.current_app.logger.error("No valid numbers found in {}".format(to))
            raise ValueError("No valid numbers found for RCS delivery")
