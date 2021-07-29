from test_admin_csv import test_admin_csv  # type: ignore
from test_admin_one_off import test_admin_one_off  # type: ignore
from test_api_bulk import test_api_bulk  # type: ignore
from test_api_one_off import test_api_one_off  # type: ignore

if __name__ == "__main__":
    for notification_type in ["email", "sms"]:
        test_admin_one_off(notification_type)
        test_admin_csv(notification_type)
        test_api_one_off(notification_type)
        test_api_bulk(notification_type)
