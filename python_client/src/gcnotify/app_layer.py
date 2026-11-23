from dataclasses import dataclass
import base64
from typing import Optional, Any, Literal, NewType, Union

from .api import GCNotifyAPI

# (UUID Types)
NotificationUUID    = NewType('NotificationUUID', str)
TemplateUUID        = NewType('TemplateUUID', str)
JobUUID             = NewType('JobUUID', str)
CategoryUUID        = NewType('CategoryUUID', str)
FolderUUID          = NewType('FolderUUID', str)
ReportUUID          = NewType('ReportUUID', str)

CSV = NewType('CSV', str)


class GCNotify(GCNotifyAPI):

    @dataclass
    class Personalisation:
        '''
        for template variables, such as
        ```{'first_name': 'John', 'last_name': 'Doe'}
        ```

        ---

        files can be attached using sub-dict,
        such as
        ```{
            "link_to_file": {
                "file": "File as base64 string",
                "filename": "your_file_name.pdf",
                "sending_method": "link"
            }
        }
        ```

        Alternatively, they can be attached directly using base64 string:
        ```{
            "application_file": {
                "file": "File as base64 string",
                "filename": "your_file_name.txt",
                "sending_method": "attach"
            },
            "other_file": {
                "file": "File as base64 string",
                "filename": "your_other_file.txt",
                "sending_method": "attach"
            }
        }
        ```
        '''
        values: dict[str, Any]

        @staticmethod
        def bytes_to_base64(b):
            return base64.b64encode(b)

        def to_dict(self) -> dict[str, Any]:
            return self.values

    def __init__(self, api_key, base_url = "https://api.notification.canada.ca", timeout = 30, enable_jsonsafe = True, _Tee = None, _trace = True):
        super().__init__(api_key, base_url, timeout, enable_jsonsafe, _Tee, _trace)

    # (NOTIFICATIONS)

    async def notifications_list(
            self,
            status: Optional[Union[
                Literal['pending', 'created', 'in-transit', 'sent', 'delivered', 'failed'],
                list[Literal['pending', 'created', 'in-transit', 'sent', 'delivered', 'failed']]
            ]] = None,
            template_type: Optional[Literal['sms', 'email']] = None,
            reference: Optional[Union[NotificationUUID, str]] = None,  # Reference Identifier for the Notification
            older_than: Optional[Union[NotificationUUID, str]] = None,
            include_jobs: Optional[bool] = False
        ):
        '''
        Retrieve a paginated list of notifications with optional filtering
        '''

        params: dict[str, Any] = {}
        for key, value in [
            ('status', status),
            ('template_type', template_type),
            ('reference', reference),
            ('older_than', older_than),
            ('include_jobs', include_jobs)
        ]:
            params = GCNotifyAPI._strap(params, key, value)

        result = await self.request(
            'GET', '/v2/notifications',
            params=params
        )
        return result

    async def notifications_list_bulk(
            self,
            older_than: Optional[Union[NotificationUUID, str]] = None
        ):
        '''
        Retrieve a paginated list of bulk jobs and their statuses
        '''

        params: dict[str, Any] = {}
        params = GCNotifyAPI._strap(params, 'older_than', older_than)

        result = await self.request(
            'GET', '/v2/notifications/bulk',
            params=params
        )

        return result

    async def notifications_bulk(
            self,
            name_of_notification: str,  # Name of the Notification
            template_id: Union[TemplateUUID, str],
            data: Union[CSV, str, list[list[str]]],
            reference: Optional[str] = None,
            reply_to_id: Optional[Union[NotificationUUID, str]] = None,
            scheduled_for: Optional[str] = None
        ):
        '''
        Send notifications in bulk, up to 50,000 recipients at a time, for a single template.

        You can schedule to send notifications up to 4 days in advance.

        :param name_of_notification: The name of the notification, such as `"January Appointment Reminders"`
        :param template_id: The Template UUID of the notification, such as `"12345678-1234-1234-1234-123456789012"`
        :param data: Comma-separated value string, or a `list[list[str]]` of data; columns: `phone number` and `name` | OR | `email address` and `name`.

        ---

        Scheduled bulk notifications with a ref for tracking and reply to address.
        
        :param reference: Ref tracking identifier such as `"january-reminders"`
        :param reply_to_id: "Reply to" address, such as `"12345678-1234-1234-1234-123456789012"`
        :param scheduled_for: **ISO 8601 date-time** string in the format `YYYY-MM-DDTHH:MM:SS` such as `"2025-06-25T15:15:00"`
        '''

        if isinstance(data, str):
            data_form = 'csv'
        elif isinstance(data, list):
            data_form = 'rows'
        else:
            raise TypeError(f'Type {type(data)} not allowed for data.')

        j: dict[str, Any] = {}
        for key, value in [
            ('name', name_of_notification),
            ('reference', reference),
            ('reply_to_id', reply_to_id),
            (data_form, data),
            ('scheduled_for', scheduled_for),
            ('template_id', template_id),
        ]:
            j = GCNotifyAPI._strap(j, key, value)

        result = await self.request(
            'POST', '/v2/notifications/bulk',
            json=j
        )

        return result

    async def notifications_bulk_cancel(
            self,
            job_id: Union[JobUUID, str]
        ):
        '''
        Cancel a bulk notification job that is scheduled but has not started sending yet
        '''

        result = await self.request(
            'DELETE', f'/v2/notifications/bulk/{job_id}'
        )

        return result

    async def notifications_bulk_status(
            self,
            job_id: Union[JobUUID, str]
        ):
        '''
        Retrieve a bulk job and its current status
        '''

        result = await self.request(
            'GET', f'/v2/notifications/bulk/{job_id}'
        )

        return result

    async def notifications_email(
            self,
            email_address: str,
            template_id: Union[TemplateUUID, str],
            personalisation: Optional[Union["GCNotify.Personalisation", dict[str, Any]]] = None,
            scheduled_for: Optional[str] = None,
            reference: Optional[str] = None,
            email_reply_to_id: Optional[str] = None
        ):
        '''
        Create and send email notification.

        :param email_address: Email of recipient.
        :param template_id: The template ID to use for the notification.

        ---

        :param personalisation: `dict` or `Personalisation` (for template variables)
        :param reference: Optional reference identifier for this notification.
        :param email_reply_to_id: Optional ID of the reply-to address to use.
        :param scheduled_for: **ISO 8601 date-time** string in the format `YYYY-MM-DDTHH:MM:SS` such as `"2025-06-25T15:15:00"`
        '''

        personalisation_data = (
            personalisation.to_dict()
            if isinstance(personalisation, GCNotify.Personalisation)
            else personalisation
        )

        j: dict[str, Any] = {}
        for key, value in [
            ('email_address', email_address),
            ('template_id', template_id),
            ('personalisation', personalisation_data),
            ('scheduled_for', scheduled_for),
            ('reference', reference),
            ('email_reply_to_id', email_reply_to_id)
        ]:
            j = GCNotifyAPI._strap(j, key, value)

        result = await self.request(
            'POST', '/v2/notifications/email',
            json=j
        )

        return result

    async def notifications_sms(
            self,
            phone_number: str,
            template_id: Union[TemplateUUID, str],
            scheduled_for: Optional[str] = None,
            personalisation: Optional[Union["GCNotify.Personalisation", dict[str, Any]]] = None,
            reference: Optional[str] = None,
            sms_sender_id: Optional[str] = None
        ):

        '''
        :param phone_number: Phone number of the recipient, such as `"+16135550123"`
        :param template_id: The template ID to use for the notification.

        ---

        :param personalisation: Dict for template variables,
            such as `{'first_name': 'John', 'last_name': 'Doe'}`;

        :param reference: Optional reference identifier for this notification.
        :param sms_sender_id: Optional ID of the SMS sender to use.
        :param scheduled_for: **ISO 8601 date-time** string in the format `YYYY-MM-DDTHH:MM:SS` such as `"2025-06-25T15:15:00"`
        
        '''

        personalisation_data = (
            personalisation.to_dict()
            if isinstance(personalisation, GCNotify.Personalisation)
            else personalisation
        )

        j: dict[str, Any] = {}
        for key, value in [
            ('phone_number', phone_number),
            ('template_id', template_id),
            ('personalisation', personalisation_data),
            ('scheduled_for', scheduled_for),
            ('reference', reference),
            ('sms_sender_id', sms_sender_id)
        ]:
            j = GCNotifyAPI._strap(j, key, value)

        result = await self.request(
            'POST', '/v2/notifications/sms',
            json=j
        )

        return result

    async def notifications_delete(
            self,
            notification_id: Union[NotificationUUID, str]
        ):
        '''
        Delete a one-off scheduled notification that has not yet been sent
        '''

        result = await self.request(
            'DELETE', f'/v2/notifications/{notification_id}'
        )

        return result

    async def notifications(
            self,
            notification_id: Union[NotificationUUID, str]
        ):
        '''
        Retrieve a specific notification by its ID
        '''

        result = await self.request(
            'GET', f'/v2/notifications/{notification_id}'
        )

        return result

    
    # (TEMPLATES)

    async def template(
            self,
            template_id: TemplateUUID
        ):
        '''
        Retrieve a specific template by its ID
        '''

        result = await self.request(
            'GET', f'/v2/template/{template_id}'
        )

        return result

    async def templates(
            self,
            template_type: Optional[Literal['sms', 'email']] = None
        ):
        '''
        Retrieve a list of templates. Filterable by template type
        '''

        if template_type:
            url = f'/v2/templates?type={template_type}'
        else:
            url = '/v2/templates'

        result = await self.request(
            'GET', url
        )

        return result


    # (TEMPLATE MANAGEMENT)

    async def manage_template_create_template(
            self,
            name: str,
            content: str,
            template_category_id: Union[CategoryUUID, str],
            template_type: Literal['sms', 'email'] = 'sms',
            email_parent_folder_id: Optional[Union[FolderUUID, str]] = None,
            email_subject: Optional[str] = None
        ):
        '''
        Create a new template with a required template category.

        This endpoint requires a NEW API key with the manage_templates permission.
        
        :param name: The name of the notification template, such as `'Service update'`
        :param content: The content of the notification template (use parenthesis to divide personalisation), 
            such as `"Hello ((name)), your service update is ready."`
        :param template_category_id: The UUID of the template category.
        :param template_type: Specify template as SMS or Email template.

        ---
        `email_subject` is required with `template_type=='email'`.

        :param email_parent_folder_id: Optional parent folder UUID for emails.
        :param email_subject: Subject of the email, such as `"Your update"`
        '''

        if template_type == 'email' and not email_subject:
            raise ValueError('Email subject cannot be blank when creating an email template.')

        j: dict[str, Any] = {}
        for key, value in [
            ('template_type', template_type),
            ('name', name),
            ('content', content),
            ('template_category_id', template_category_id),
            ('subject', email_subject),
            ('parent_folder_id', email_parent_folder_id)
        ]:
            j = GCNotifyAPI._strap(j, key, value)

        result = await self.request(
            'POST', '/v2/manage-template',
            json=j
        )

        return result

    async def manage_template_get_categories(self):
        '''
        Retrieve all available template categories for manage template operations.

        This endpoint requires a NEW API key with the manage_templates permission.
        '''

        result = await self.request(
            'GET', '/v2/manage-template/template-categories'
        )

        return result

    async def manage_template_archive_template(
            self,
            template_id: Union[TemplateUUID, str]
        ):
        '''
        Archive a template and remove it from any folder.

        This endpoint requires a NEW API key with the manage_templates permission.
        '''

        result = await self.request(
            'DELETE', f'/v2/manage-template/{template_id}'
        )

        return result

    async def manage_template_get_template(
            self,
            template_id: Union[TemplateUUID, str]
        ):
        '''
        Retrieve a specific template by ID using manage template permissions.

        This endpoint requires a NEW API key with the manage_templates permission.
        '''

        result = await self.request(
            'GET', f'/v2/manage-template/{template_id}'
        )

        return result

    # NOTE : This is split into two parts.
    async def manage_template_update_folder(
            self,
            template_id: Union[TemplateUUID, str],
            parent_folder_id: Optional[Union[FolderUUID, str]] = None
        ):
        '''
        Update editable fields on a template,
        **parent folder assignment.**

        This endpoint requires a NEW API key with the manage_templates permission.

        :param template_id: The UUID of the template.
        :param parent_folder_id: Specify parent folder UUID, or leave blank to unassign.
        '''

        # NOTE : JS uses `null`, not `None`, impact unknown
        result = await self.request(
            'PATCH', f'/v2/manage-template/{template_id}',
            json={'parent_folder_id': parent_folder_id}
        )

        return result

    async def manage_template_update_name_and_category(
            self,
            template_id: Union[TemplateUUID, str],
            name: str,
            template_category_id: Union[CategoryUUID, str]
        ):
        '''
        Update editable fields on a template,
        **name & category.**

        This endpoint requires a NEW API key with the manage_templates permission.

        :param template_id: The UUID of the template.
        :param name: New name of the template, such as `"Follow-up reminder"`
        :param template_category_id: The UUID of the category.
        '''

        result = await self.request(
            'PATCH', f'/v2/manage-template/{template_id}',
            json={'name': name, 'template_category_id': template_category_id}
        )

        return result


    # (TEMPLATE FOLDER MANAGEMENT)

    async def manage_template_folder_get_folders(self):
        '''
        Retrieve all template folders for the service.

        This endpoint requires a NEW API key with the manage_templates permission.
        '''

        result = await self.request(
            'GET', '/v2/manage-template-folder'
        )

        return result

    async def manage_template_folder_create_folder(
            self,
            name:str,
            parent_folder_id: Optional[Union[FolderUUID, str]] = None
        ):
        '''
        Create a new template folder, either at the root of the service or inside a parent folder.

        Root folders are shared with all active users on the service. Subfolders inherit user access from their parent folder.

        This endpoint requires a NEW API key with the manage_templates permission.

        :param name: The name of the folder, such as `"January Reminders"`
        :param parent_folder_id: Create a folder inside another folder by specifying
            the parent folder ID. If `None`, the folder will be created in the root directory.
        '''

        j: dict[str, Any] = {}
        for key, value in [
            ('name', name),
            ('parent_folder_id', parent_folder_id)
        ]:
            j = GCNotifyAPI._strap(j, key, value)

        result = await self.request(
            'POST', '/v2/manage-template-folder',
            json=j
        )

        return result

    async def manage_template_folder_delete_folder(
            self,
            template_folder_id: Union[FolderUUID, str]
        ):
        '''
        Delete an empty template folder. The folder must not contain any templates or subfolders.

        This endpoint requires a NEW API key with the manage_templates permission.
        '''

        result = await self.request(
            'DELETE', f'/v2/manage-template-folder/{template_folder_id}'
        )

        return result

    async def manage_template_folder_get_folder(
            self,
            template_folder_id: Union[FolderUUID, str]
        ):
        '''
        Retrieve a specific template folder by ID.

        This endpoint requires a NEW API key with the manage_templates permission.
        '''

        result = await self.request(
            'GET', f'/v2/manage-template-folder/{template_folder_id}'
        )

        return result

    async def manage_template_folder_move_folder(
            self,
            template_folder_id: Union[FolderUUID, str],
            parent_folder_id: Optional[Union[FolderUUID, str]] = None
        ):
        '''
        Move a template folder to a different parent folder. Set parent_folder_id to `None` to move the folder to the root of the service.

        When a folder is moved into a parent folder, it and its subfolders are only visible to users who also have access to the new parent folder.

        This endpoint requires a NEW API key with the manage_templates permission.
        '''

        result = await self.request(
            'PATCH', f'/v2/manage-template-folder/{template_folder_id}',
            json={'parent_folder_id': parent_folder_id}
        )

        return result

    
    async def manage_template_folder_rename_folder(
            self,
            template_folder_id: Union[FolderUUID, str],
            name: str
        ):
        '''
        Rename a template folder. 

        This endpoint requires a NEW API key with the manage_templates permission.
        '''

        result = await self.request(
            'PATCH', f'/v2/manage-template-folder/{template_folder_id}',
            json={'name': name}
        )

        return result


    # (REPORTS)

    async def reports(
            self,
            older_than: Optional[Union[ReportUUID, str]] = None
        ):
        '''
        Retrieve a paginated list of reports for the authenticated service
        '''

        result = await self.request(
            'GET', '/v2/reports',
            params=(
                {'older_than': older_than}
                if older_than is not None
                else None
            )
        )

        return result

    async def reports_request(
            self,
            language: Union[Literal['en', 'fr'], str] = 'en',
            report_type: Literal['sms', 'email', 'job'] = 'sms',
            job_id: Optional[Union[JobUUID, str]] = None
        ):
        '''
        Request the generation of a report. Reports are generated asynchronously; 
        poll the report by ID to check its status before downloading its content.

        :param job_id: Specify the Job ID if `report_type=='job'`
        '''

        if report_type == 'job' and job_id is None:
            raise ValueError('A job ID is required for job reports.')
        if report_type != 'job' and job_id is not None:
            raise ValueError('A job ID can only be specified for job reports.')

        j: dict[str, Any] = {}
        for key, value in [
            ('language', language),
            ('report_type', report_type),
            ('job_id', job_id)
        ]:
            j = GCNotifyAPI._strap(j, key, value)

        result = await self.request(
            'POST', '/v2/reports',
            json=j
        )

        return result

    async def reports_get_report(
            self,
            report_id: Union[ReportUUID, str]
        ):
        '''
        Retrieve a specific report by its ID.
        '''

        result = await self.request(
            'GET', f'/v2/reports/{report_id}'
        )

        return result

    async def reports_get_report_content(
            self,
            report_id: Union[ReportUUID, str],
            _accept: str = 'text/csv'
        ):
        '''
        Download the generated report content as a CSV file. The report must have a status of ready.
        '''

        result = await self.request(
            'GET', f'/v2/reports/{report_id}/content',
            accept=_accept
        )

        return result