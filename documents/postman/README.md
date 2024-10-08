# Postman

To download Postman, go [here](https://www.postman.com/downloads/). Postman allows you to send requests.

## Postman collection

The intention of this collection is to provide quick, easy functionality to send email, sms, and push notifications.  This collection can be used by business line users integrating with VA Notify to get familiar with the API and send test notifications.  

The postman scripts use the environment variables and populate or update them as the scripts are executed. These files can be imported into Postman and allow you to 
execute the basic endpoints once the environmental variables below are populated. 

Creation, viewing and editing of templates can be done in the Self Service Portal.
## basic environment variables

These environment variables should be defined before you can execute any of the scripts
- notification-api-url: `{environment}-api.va.gov/vanotify` - Publically available outside the VPN. 
- notification-api-url-private: `https://{environment}.api.notifications.va.gov - Privately available inside the VPN. 
- service-api-key : The VA Notify team creates an api key and sends it via encrypted email.
- service-id : Retrieve this from the portal.
- template-id : Retrieve this from the portal. 
## basic notification calls

See Postman collection for details of call to send email, sms, or mobile push. Using the collection, you can take the following actions: 

- You can send an email with an email address or a recipient-identifier, so VA Notify can look up the email address.
- You can send a text with a phone number or a recipient-identifier, so VA Notify can look up the email address. 
- You can send a push notification to a Mobile App user. 
- You can get information regarding the status of a notification.

### Example
`````

curl -x POST https:://api-staging.va.gov/vanotify/v2/notifications/email \
 -h 
 -d '{
    "template_id": "{{email-template-id}}",
    "email_address": "john.smith@fake-domain.com"
}
`````

#### Response
`````
{
  "billing_code": null,
  "callback_url": null,
  "content": {
    "body": "Test",
    "subject": "Test"
  },
  "id": "<notification-id>",
  "reference": null,
  "scheduled_for": null,
  "template": {
    "id": "<template-id>",
    "uri": "https://dev-api.va.gov/services/<service-id>/templates/<template-id>",
    "version": 1
  },
  "uri": "https://dev-api.va.gov/v2/notifications/<notification-id>"
}
`````