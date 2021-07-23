from test_api_email import test_api_email
from test_api_sms import test_api_sms
from test_api_email_bulk import test_api_email_bulk
from test_admin_email_one_off import test_admin_email_one_off

if __name__ == "__main__":
    test_api_email()
    test_api_email_bulk()
    test_admin_email_one_off()
    test_api_sms()
