import click
import boto3
from notifications_python_client.notifications import NotificationsAPIClient


def read_from_ssm(key: str) -> str:
    boto_client = boto3.client('ssm')
    resp = boto_client.get_parameter(Name=f'/utility/locust/perf/{key}', WithDecryption=True)
    return resp['Parameter']['Value']


@click.command()
@click.option('--count', default=1, help='Number of messages to send.')
@click.option('--phone', help='Phone number to send messages to')
def send_sms(
    count,
    phone,
):
    sms_template_id = read_from_ssm('sms_template_id')
    service_id = read_from_ssm('service_id')
    sms_sender_id = read_from_ssm('sms_sender_id')
    _api_key = read_from_ssm('api_key')
    api_key = f'some_key-{service_id}-{_api_key}'

    notifications_client = NotificationsAPIClient(api_key, base_url='https://perf.api.notifications.va.gov')
    for x in range(count):
        response = notifications_client.send_sms_notification(
            phone_number=phone, template_id=sms_template_id, sms_sender_id=sms_sender_id
        )
        print(f'Sent sms with id: {response["id"]}')


if __name__ == '__main__':
    send_sms()
