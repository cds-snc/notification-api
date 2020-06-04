# Postman scripts

The postman scripts use the environment variables and populate or update them as the scripts are executed.

The basic environment variables are in this folder which you cna import along with the scripts.  

## basic environment variables

These environment variables should be defined before you can execute any of the scripts
- notification-api
-- the DNS name of the Notification API URL. This is the AWS load balancer dns name.  If you run the notification API \
on your local, then this should be a value recognized by postman such as localhost.
- notification-secret
-- the secret key that is used to generate JWT.  You can see its value at `arn:aws:ssm:<aws region>:<aws id>:parameter/dev/notification-api/secret-key`
- notification-admin-id
-- the admin id

Some scripts depend on the environment variables set by other scripts.  So depends on your goal you might have to run \
the scripts in the order they are listed in postman.