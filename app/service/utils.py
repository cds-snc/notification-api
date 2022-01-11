from app.clients.email import EmailClient
import itertools

from flask import current_app

from notifications_utils.recipients import allowed_to_send_to

from app.models import (
    KEY_TYPE_TEST, KEY_TYPE_TEAM, KEY_TYPE_NORMAL, Service)


def service_allowed_to_send_to(recipient, service, key_type, allow_whitelisted_recipients=True):
    if key_type == KEY_TYPE_TEST:
        return True

    if key_type == KEY_TYPE_NORMAL and not service.restricted:
        return True

    team_members = itertools.chain.from_iterable(
        [user.mobile_number, user.email_address] for user in service.users
    )
    whitelist_members = [
        member.recipient for member in service.whitelist
        if allow_whitelisted_recipients
    ]

    if (
        (key_type == KEY_TYPE_NORMAL and service.restricted) or (key_type == KEY_TYPE_TEAM)
    ):
        return allowed_to_send_to(
            recipient,
            itertools.chain(
                team_members,
                whitelist_members
            )
        )


def compute_source_email_address(service: Service, provider: EmailClient) -> str:
    sending_domain = next(
        domain for domain in
        [service.sending_domain, provider.email_from_domain, current_app.config['NOTIFY_EMAIL_FROM_DOMAIN']]
        if domain is not None)

    email_from = next(
        email for email in
        [service.email_from, provider.email_from_user, current_app.config['NOTIFY_EMAIL_FROM_USER']]
        if email is not None)

    return f'"{current_app.config["NOTIFY_EMAIL_FROM_NAME"]}" <{email_from}@{sending_domain}>'
