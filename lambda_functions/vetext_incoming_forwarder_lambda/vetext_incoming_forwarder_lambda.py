import json
import http.client
import os 
import boto3
import pprint
import urllib.parse

def lambda_handler(event, context):
    connection = http.client.HTTPSConnection(os.environ['vetext_api_endpoint_domain'])
    headers = {'Content-type': 'application/json', 'Authorization': os.environ['vetext_api_endpoint_auth']}
    
    pp = pprint.PrettyPrinter(indent=4)
    
    eventBody = urllib.parse.parse_qs(event["body"]) 
    
    pp.pprint(eventBody)
 
    body = {
        "accountSid": eventBody.get("AccountSid", ""),
        "messageSid": eventBody.get("MessageSid", ""),
    	"messagingServiceSid": "",
    	"to": eventBody.get("To", ""),
    	"from": eventBody.get("From", ""),
    	"messageStatus": eventBody.get("SmsStatus", ""),
        "body": eventBody.get("Body", "")
        }
    
    json_data = json.dumps(body)
    
    connection.request('POST', os.environ['vetext_api_endpoint_path'], json_data, headers)

    response = connection.getresponse()
    
    if response.status == 200:
        return {
            'statusCode': 200,
            'body': response.read().decode()
        }
    else:
        sqs = boto3.client('sqs')
        queue_url = os.environ['vetext_request_drop_sqs_url']
        
        queue_msg = json.dumps(event)
        queue_msg_attrs = {
                            'source': {
                                'DataType': 'String',
                                'StringValue': 'twilio'
                            }
                          }
        
        sqs.send_message(QueueUrl=queue_url,
                         MessageAttributes=queue_msg_attrs,
                         MessageBody=queue_msg)
        return {
            'statusCode': response.status,
            'body': response.read().decode()
        }