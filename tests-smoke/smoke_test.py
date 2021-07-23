from test_admin_email_one_off import test_admin_email_one_off
from test_admin_sms_one_off import test_admin_sms_one_off
from test_api_email import test_api_email
from test_api_sms import test_api_sms
from test_api_email_bulk import test_api_email_bulk
from test_api_sms_bulk import test_api_sms_bulk

if __name__ == "__main__":
    test_api_email()
    test_api_email_bulk()
    test_api_sms()
    test_api_sms_bulk()

    test_admin_email_one_off()
    test_admin_sms_one_off()
