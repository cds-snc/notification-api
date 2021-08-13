from smoke.common import Notification_type
from smoke.test_admin_csv import test_admin_csv
from smoke.test_admin_one_off import test_admin_one_off
from smoke.test_api_bulk import test_api_bulk
from smoke.test_api_one_off import test_api_one_off

if __name__ == "__main__":
    for notification_type in [Notification_type.EMAIL]:
        test_admin_one_off(notification_type)
        test_admin_csv(notification_type)
        test_api_one_off(notification_type)
        test_api_bulk(notification_type)
