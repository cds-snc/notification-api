import boto3
from flask import current_app

import hmac  # required to compute the HMAC key
import hashlib  # required to create a SHA256 hash
import base64  # required to encode the computed key
import time


def smtp_add(name):
    ses_client = boto3.client(
        'ses',
        aws_access_key_id=current_app.config["AWS_SES_ACCESS_KEY"],
        aws_secret_access_key=current_app.config["AWS_SES_SECRET_KEY"],
        region_name=current_app.config["AWS_SES_REGION"])
    r53_client = boto3.client(
        'route53',
        aws_access_key_id=current_app.config["AWS_SES_ACCESS_KEY"],
        aws_secret_access_key=current_app.config["AWS_SES_SECRET_KEY"],
        region_name=current_app.config["AWS_SES_REGION"])
    iam_client = boto3.client(
        'iam',
        aws_access_key_id=current_app.config["AWS_SES_ACCESS_KEY"],
        aws_secret_access_key=current_app.config["AWS_SES_SECRET_KEY"],
        region_name=current_app.config["AWS_SES_REGION"])

    name = name + '.m.' + current_app.config["NOTIFY_EMAIL_DOMAIN"]

    token = create_domain_identity(ses_client, name)
    add_record(r53_client, '_amazonses.' + name, "\"%s\"" % token, "TXT")

    tokens = get_dkim(ses_client, name)
    for token in tokens:
        add_record(
            r53_client,
            token + "._domainkey." + name,
            token + ".dkim.amazonses.com",
        )

    add_record(r53_client, name, "\"v=spf1 include:amazonses.com ~all\"", "TXT")
    add_record(
        r53_client,
        "_dmarc." + name,
        "\"v=DMARC1; p=none; sp=none; rua=mailto:dmarc@cyber.gc.ca; ruf=mailto:dmarc@cyber.gc.ca\"",
        "TXT")

    credentials = add_user(iam_client, name)
    return credentials


def smtp_get_user_key(name):
    try:
        iam_client = boto3.client(
            'iam',
            aws_access_key_id=current_app.config["AWS_SES_ACCESS_KEY"],
            aws_secret_access_key=current_app.config["AWS_SES_SECRET_KEY"],
            region_name=current_app.config["AWS_SES_REGION"])
        return iam_client.list_access_keys(
            UserName=name,
        )["AccessKeyMetadata"][0]["AccessKeyId"]
    except Exception as e:
        raise e


def smtp_remove(name):
    try:
        ses_client = boto3.client(
            'ses',
            aws_access_key_id=current_app.config["AWS_SES_ACCESS_KEY"],
            aws_secret_access_key=current_app.config["AWS_SES_SECRET_KEY"],
            region_name=current_app.config["AWS_SES_REGION"])
        r53_client = boto3.client(
            'route53',
            aws_access_key_id=current_app.config["AWS_SES_ACCESS_KEY"],
            aws_secret_access_key=current_app.config["AWS_SES_SECRET_KEY"],
            region_name=current_app.config["AWS_SES_REGION"])
        iam_client = boto3.client(
            'iam',
            aws_access_key_id=current_app.config["AWS_SES_ACCESS_KEY"],
            aws_secret_access_key=current_app.config["AWS_SES_SECRET_KEY"],
            region_name=current_app.config["AWS_SES_REGION"])

        [domain, _] = name.split("-")

        policies = iam_client.list_user_policies(
            UserName=name,
        )["PolicyNames"]

        for policy in policies:
            iam_client.delete_user_policy(
                UserName=name,
                PolicyName=policy
            )

        keys = iam_client.list_access_keys(
            UserName=name,
        )["AccessKeyMetadata"]

        for key in keys:
            iam_client.delete_access_key(
                UserName=name,
                AccessKeyId=key["AccessKeyId"]
            )

        iam_client.delete_user(UserName=name)
        ses_client.delete_identity(Identity=domain)
        records = r53_client.list_resource_record_sets(
            HostedZoneId=current_app.config["AWS_ROUTE53_ZONE"],
            MaxItems="6",  # Change this if # records per domain are changed
            StartRecordName=domain
        )["ResourceRecordSets"]

        for record in records:
            if domain in record["Name"]:
                delete_record(r53_client, record)

        return True

    except Exception as e:
        raise e


def create_domain_identity(client, name):
    try:
        return client.verify_domain_identity(
            Domain=name
        )['VerificationToken']
    except Exception as e:
        raise e


def get_dkim(client, name):
    try:
        return client.verify_domain_dkim(
            Domain=name
        )['DkimTokens']
    except Exception as e:
        raise e


def add_user(client, name):
    try:
        user_name = name + "-" + str(int(time.time()))
        client.create_user(
            Path='/notification-smtp/',
            UserName=user_name,
            Tags=[
                {
                    'Key': 'SMTP-USER',
                    'Value': name
                },
            ]
        )

        client.put_user_policy(
            PolicyDocument=generate_user_policy(name),
            PolicyName="SP-" + user_name,
            UserName=user_name
        )

        response = client.create_access_key(
            UserName=user_name
        )

        credentials = {
            "iam": user_name,
            "domain": name,
            "name": current_app.config["AWS_SES_SMTP"],
            "port": "465",
            "tls": "Yes",
            "username": response["AccessKey"]["AccessKeyId"],
            "password": munge(response["AccessKey"]["SecretAccessKey"])
        }

        return credentials
    except Exception as e:
        raise e


def add_record(client, name, value, record_type="CNAME"):
    try:
        client.change_resource_record_sets(
            HostedZoneId=current_app.config["AWS_ROUTE53_ZONE"],
            ChangeBatch={
                'Comment': 'add %s -> %s' % (name, value),
                'Changes': [
                    {
                        'Action': 'UPSERT',
                        'ResourceRecordSet': {
                            'Name': name,
                            'Type': record_type,
                            'TTL': 300,
                            'ResourceRecords': [{'Value': value}]
                        }
                    }]
            })
    except Exception as e:
        raise e


def delete_record(client, record):
    try:
        client.change_resource_record_sets(
            HostedZoneId=current_app.config["AWS_ROUTE53_ZONE"],
            ChangeBatch={
                'Comment': 'Deleted',
                'Changes': [
                    {
                        'Action': 'DELETE',
                        'ResourceRecordSet': record
                    }
                ]
            }
        )
    except Exception as e:
        raise e


def generate_user_policy(name):
    policy = (
        '{"Version":"2012-10-17","Statement":'
        '[{"Effect":"Allow","Action":["ses:SendRawEmail"],"Resource":"*",'
        '"Condition":{"StringLike":{"ses:FromAddress":"*@%s"}}}]}' % name)
    return policy

# Taken from https://docs.aws.amazon.com/ses/latest/DeveloperGuide/example-create-smtp-credentials.html


def munge(secret):
    message = 'SendRawEmail'
    version = '\x02'

    # Compute an HMAC-SHA256 key from the AWS secret access key.
    signatureInBytes = hmac.new(secret.encode('utf-8'), message.encode('utf-8'), hashlib.sha256).digest()
    # Prepend the version number to the signature.
    signatureAndVersion = version.encode('utf-8') + signatureInBytes
    # Base64-encode the string that contains the version number and signature.
    smtpPassword = base64.b64encode(signatureAndVersion)
    # Decode the string and print it to the console.
    return smtpPassword.decode('utf-8')
