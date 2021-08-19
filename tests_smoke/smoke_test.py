from smoke.common import Config, Notification_type
from smoke.test_admin_csv import test_admin_csv
from smoke.test_admin_one_off import test_admin_one_off
from smoke.test_api_bulk import test_api_bulk
from smoke.test_api_one_off import test_api_one_off

if __name__ == "__main__":
    print("API Smoke test\n")
    for key in ["API_HOST_NAME", "SERVICE_ID", "EMAIL_TEMPLATE_ID", "SMS_TEMPLATE_ID", "EMAIL_TO", "SMS_TO"]:
        print(f"{key:>17}: {Config.__dict__[key]}")
    print("")

    for notification_type in [Notification_type.EMAIL, Notification_type.SMS]:
        test_admin_one_off(notification_type)
        test_admin_csv(notification_type)
        test_api_one_off(notification_type)
        test_api_bulk(notification_type)
