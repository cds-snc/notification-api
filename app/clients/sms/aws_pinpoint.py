from time import monotonic

import boto3
import phonenumbers

from app.clients.sms import SmsClient, SmsSendingVehicles


class AwsPinpointClient(SmsClient):
    """
    AWS Pinpoint SMS client
    """

    def init_app(self, current_app, statsd_client, *args, **kwargs):
        self._client = boto3.client("pinpoint-sms-voice-v2", region_name="ca-central-1")
        super(AwsPinpointClient, self).__init__(*args, **kwargs)
        self.current_app = current_app
        self.name = "pinpoint"
        self.statsd_client = statsd_client

    def get_name(self):
        return self.name

    def send_sms(self, to, content, reference, multi=True, sender=None, template_id=None, service_id=None, sending_vehicle=None):
        messageType = "TRANSACTIONAL"
        matched = False
        opted_out = False
        response = {}

        use_shortcode_pool = (
            sending_vehicle == SmsSendingVehicles.SHORT_CODE or str(service_id) == self.current_app.config["NOTIFY_SERVICE_ID"]
        )
        if use_shortcode_pool:
            pool_id = self.current_app.config["AWS_PINPOINT_SC_POOL_ID"]
        else:
            pool_id = self.current_app.config["AWS_PINPOINT_DEFAULT_POOL_ID"]

        for match in phonenumbers.PhoneNumberMatcher(to, "US"):
            matched = True
            opted_out = False
            to = phonenumbers.format_number(match.number, phonenumbers.PhoneNumberFormat.E164)
            destinationNumber = to
            try:
                start_time = monotonic()
                # For international numbers we send with an AWS number for the corresponding country, using our default sender id.
                # Note that Canada does not currently support sender ids.
                if phonenumbers.region_code_for_number(match.number) != "CA":
                    response = self._client.send_text_message(
                        DestinationPhoneNumber=destinationNumber,
                        MessageBody=content,
                        MessageType=messageType,
                        ConfigurationSetName=self.current_app.config["AWS_PINPOINT_CONFIGURATION_SET_NAME"],
                    )
                else:
                    dryrun = destinationNumber == self.current_app.config["DRYRUN_TEST_NUMBER"]
                    response = self._client.send_text_message(
                        DestinationPhoneNumber=destinationNumber,
                        OriginationIdentity=pool_id,
                        MessageBody=content,
                        MessageType=messageType,
                        ConfigurationSetName=self.current_app.config["AWS_PINPOINT_CONFIGURATION_SET_NAME"],
                        DryRun=dryrun,
                    )
                    if dryrun:
                        self.current_app.logger.info(
                            f"SMS with message id {response.get('MessageId')} is sending to DRYRUN_TEST_NUMBER. Boto call made to AWS, but not send on."
                        )
            except self._client.exceptions.ConflictException as e:
                if e.response.get("Reason") == "DESTINATION_PHONE_NUMBER_OPTED_OUT":
                    opted_out = True
                else:
                    raise e

            except Exception as e:
                self.statsd_client.incr("clients.pinpoint.error")
                raise e
            finally:
                elapsed_time = monotonic() - start_time
                self.current_app.logger.info("AWS Pinpoint request finished in {}".format(elapsed_time))
                self.statsd_client.timing("clients.pinpoint.request-time", elapsed_time)
                self.statsd_client.incr("clients.pinpoint.success")
            return "opted_out" if opted_out else response.get("MessageId")

        if not matched:
            self.statsd_client.incr("clients.pinpoint.error")
            self.current_app.logger.error("No valid numbers found in {}".format(to))
            raise ValueError("No valid numbers found for SMS delivery")
