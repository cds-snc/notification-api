# notification-admin Changes Required

This document outlines the changes needed in the notification-admin repository to complement the suppression list removal feature implemented in notification-api.

## Overview

The notification-admin needs to provide a UI under the service settings page where users can:
1. Input an email address
2. Check if it's on the suppression list
3. Remove it from the suppression list (if the service has sent to it before)

## Required Changes

### 1. Add Route in `app/main/views/service_settings.py`

Add a new route for the suppression list management page:

```python
@main.route("/services/<uuid:service_id>/service-settings/suppression-list", methods=["GET", "POST"])
@user_has_permissions("manage_service")
def service_suppression_list(service_id):
    """
    Page to manage suppression list for a service.
    Allows removing email addresses from the SES suppression list.
    """
    from app.main.forms import SuppressionListRemovalForm
    
    form = SuppressionListRemovalForm()
    
    if form.validate_on_submit():
        email_address = form.email_address.data
        
        try:
            # Call notification-api endpoint to remove from suppression list
            service_api_client.remove_email_from_suppression_list(
                service_id,
                email_address
            )
            
            flash(
                f"Successfully removed {email_address} from the suppression list.",
                "default_with_tick"
            )
            return redirect(url_for(".service_suppression_list", service_id=service_id))
            
        except HTTPError as e:
            if e.status_code == 404:
                flash(
                    f"This service has not sent any emails to {email_address}. "
                    "You can only remove email addresses that your service has sent to.",
                    "error"
                )
            elif e.status_code == 400:
                flash(
                    "Invalid email address. Please check and try again.",
                    "error"
                )
            else:
                flash(
                    "Failed to remove email from suppression list. Please try again or contact support.",
                    "error"
                )
    
    return render_template(
        "views/service-settings/suppression-list.html",
        form=form
    )
```

### 2. Add Form in `app/main/forms.py`

Create a form for email address input:

```python
class SuppressionListRemovalForm(StripWhitespaceForm):
    email_address = email_address(
        "Email address",
        validators=[
            DataRequired(message="Cannot be empty"),
            ValidEmail()
        ]
    )
```

### 3. Add API Client Method in `app/notify_client/service_api_client.py`

Add method to call the notification-api endpoint:

```python
def remove_email_from_suppression_list(self, service_id, email_address):
    """
    Remove an email address from the SES suppression list.
    
    Args:
        service_id: UUID of the service
        email_address: Email address to remove from suppression list
        
    Returns:
        Response from the API
        
    Raises:
        HTTPError: If the API call fails
    """
    data = {"email_address": email_address}
    return self.post(
        url=f"/service/{service_id}/remove-from-suppression-list",
        data=data
    )
```

### 4. Create Template `app/templates/views/service-settings/suppression-list.html`

Create the HTML template:

```html
{% extends "withnav_template.html" %}
{% from "components/form.html" import form_wrapper %}
{% from "components/page-header.html" import page_header %}

{% block service_page_title %}
  Remove email from suppression list
{% endblock %}

{% block maincolumn_content %}

  {{ page_header("Remove email from suppression list") }}

  <div class="govuk-body">
    <p>
      If an email address is on the suppression list, Notify will not send emails to it. 
      This can happen if:
    </p>
    <ul class="govuk-list govuk-list--bullet">
      <li>the email server was down when we tried to send</li>
      <li>the email server gave an incorrect response</li>
      <li>an overactive spam filter blocked the email</li>
    </ul>
    
    <p>
      You can remove an email address from the suppression list if your service has 
      previously sent to it.
    </p>
    
    <div class="govuk-warning-text">
      <span class="govuk-warning-text__icon" aria-hidden="true">!</span>
      <strong class="govuk-warning-text__text">
        <span class="govuk-warning-text__assistive">Warning</span>
        Only remove email addresses that you know are valid. Repeatedly sending to 
        invalid addresses can affect your service's sending reputation.
      </strong>
    </div>
  </div>

  {% call form_wrapper() %}
    {{ form.email_address(param_extensions={"hint": {"text": "Enter the email address to remove from the suppression list"}}) }}
    {{ page_footer("Remove from suppression list") }}
  {% endcall %}

{% endblock %}
```

### 5. Add Link in Service Settings Page

In `app/templates/views/service-settings/index.html`, add a link to the suppression list management page:

```html
<div class="settings-table body-copy-table">
  <h2 class="heading-medium">Email settings</h2>
  <div class="govuk-grid-row bottom-gutter-3-2">
    <!-- Existing email settings -->
  </div>
  
  <div class="govuk-grid-row bottom-gutter-3-2">
    <div class="govuk-grid-column-two-thirds">
      <h3 class="heading-small">Suppression list</h3>
      <p class="govuk-body">
        Remove email addresses from the suppression list if they were blocked incorrectly.
      </p>
    </div>
    <div class="govuk-grid-column-one-third">
      <a href="{{ url_for('.service_suppression_list', service_id=current_service.id) }}" class="govuk-link govuk-link--no-visited-state">
        Manage suppression list
      </a>
    </div>
  </div>
</div>
```

### 6. Add Tests

Create `tests/app/main/views/service_settings/test_suppression_list.py`:

```python
import pytest
from flask import url_for
from unittest.mock import Mock
from requests import HTTPError


def test_service_suppression_list_page_renders(
    client_request,
    service_one,
    mocker
):
    """Test that the suppression list management page renders"""
    page = client_request.get(
        "main.service_suppression_list",
        service_id=service_one["id"]
    )
    
    assert "Remove email from suppression list" in page
    assert "Enter the email address" in page


def test_remove_email_from_suppression_list_success(
    client_request,
    service_one,
    mocker,
    mock_remove_email_from_suppression_list
):
    """Test successfully removing an email from suppression list"""
    client_request.post(
        "main.service_suppression_list",
        service_id=service_one["id"],
        _data={"email_address": "test@example.com"},
        _expected_redirect=url_for(
            "main.service_suppression_list",
            service_id=service_one["id"]
        )
    )
    
    mock_remove_email_from_suppression_list.assert_called_once_with(
        service_one["id"],
        "test@example.com"
    )


def test_remove_email_from_suppression_list_not_sent_by_service(
    client_request,
    service_one,
    mocker
):
    """Test error when service hasn't sent to the email"""
    mock_remove = mocker.patch(
        "app.service_api_client.remove_email_from_suppression_list",
        side_effect=HTTPError(response=Mock(status_code=404))
    )
    
    page = client_request.post(
        "main.service_suppression_list",
        service_id=service_one["id"],
        _data={"email_address": "never-sent@example.com"},
        _expected_status=200
    )
    
    assert "has not sent any emails" in page


def test_remove_email_from_suppression_list_invalid_email(
    client_request,
    service_one,
    mocker
):
    """Test validation error for invalid email"""
    page = client_request.post(
        "main.service_suppression_list",
        service_id=service_one["id"],
        _data={"email_address": "not-an-email"},
        _expected_status=200
    )
    
    assert "Not a valid email address" in page


@pytest.fixture
def mock_remove_email_from_suppression_list(mocker):
    return mocker.patch(
        "app.service_api_client.remove_email_from_suppression_list"
    )
```

## Testing the Integration

1. Start both notification-api and notification-admin locally
2. Log in to notification-admin
3. Navigate to a service's settings page
4. Click on "Manage suppression list"
5. Enter an email address that the service has sent to
6. Verify the success message appears
7. Check that a Freshdesk ticket was created
8. Verify the email is removed from the AWS SES suppression list

## Security Considerations

- The endpoint is protected by the `manage_service` permission
- Users can only remove emails their service has sent to
- All actions are logged and create Freshdesk tickets for audit trail
- Rate limiting should be considered to prevent abuse

## Additional Notes

- The feature only works for email addresses that the service has actually sent to (verified in notification-api)
- Freshdesk tickets are created automatically to track removals
- The AWS SES v2 API is used for suppression list management
- Users should be warned about the risks of repeatedly sending to invalid addresses
