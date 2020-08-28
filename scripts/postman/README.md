# Postman

To download Postman, go [here](https://www.postman.com/downloads/). Postman allows you to send requests.

## Postman scripts

The postman scripts use the environment variables and populate or update them as the scripts are executed.

The basic environment variables are in this folder which you can import along with the scripts.  

## basic environment variables

These environment variables should be defined before you can execute any of the scripts
- notification-api
-- the DNS name of the Notification API URL. This is the AWS load balancer dns name.  If you run the notification API \
on your local, then this should be a value recognized by postman such as localhost.
Run the following command to get the value:
```
aws ssm get-parameter --name /dev/notification-api/api-host-name | jq '.Parameter.Value' -r
```
- notification-secret
-- the secret key that is used to generate JWT.  You can see its value at `arn:aws:ssm:<aws region>:<aws id>:parameter/dev/notification-api/admin-client-secret`.
Run the following command to get the value:
```
 aws ssm get-parameter --name /dev/notification-api/admin-client-secret --with-decryption | jq '.Parameter.Value' -r
```
- notification-admin-id
-- the admin id (found in `config.py`)

Some scripts depend on the environment variables set by other scripts.  So depends on your goal you might have to run \
the scripts in the order they are listed in postman.

## Demo Data

When demoing, use the service and template listed in the Demo Data document of the team repo.