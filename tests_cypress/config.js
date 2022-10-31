const config = {
    STAGING: {
        API: {
            HostName: "https://api.staging.notification.cdssandbox.xyz",
        },
        Admin: {
            HostName: "https://staging.notification.cdssandbox.xyz",
            AdminUser: "alexcampbell1861@gmail.com",
        },
        Services: {
            Notify: 'd6aa2c68-a2d9-4437-ab19-3ae8eb202553'
        },
        Templates: {
            "FILE_ATTACH_TEMPLATE_ID": "7246c71e-3d60-458b-96af-af17a5b07659",
            "SIMPLE_EMAIL_TEMPLATE_ID": "939dafde-1b60-47f0-a6d5-c9080d92a4a8",
            "VARIABLES_EMAIL_TEMPLATE_ID": "1101a00a-11b7-4036-865c-add43fcff7c9"
        },
        Users: {
            Team: ['andrew.leith+bannertest@cds-snc.ca'],
            NonTeam: ['person@example.com'],
            Simulated: ['simulate-delivered@notification.canada.ca', 'simulate-delivered-2@notification.canada.ca', 'simulate-delivered-3@notification.canada.ca']
        },
        ReplyTos: {
            Default: '24e5288d-8bfa-4ad4-93aa-592c11a694cd',
            Second: '797865c4-788b-4184-91ae-8e45eb07e40b'
        }
    },
    LOCAL: {
        API: {
            HostName: "http://localhost:6011",
        },
        Templates: {
            "FILE_ATTACH_TEMPLATE_ID": "7246c71e-3d60-458b-96af-af17a5b07659",
            "SIMPLE_EMAIL_TEMPLATE_ID": "939dafde-1b60-47f0-a6d5-c9080d92a4a8",
            "VARIABLES_EMAIL_TEMPLATE_ID": "1101a00a-11b7-4036-865c-add43fcff7c9"
        },
        Users: {
            Team: ['andrew.leith+bannertest@cds-snc.ca'],
            NonTeam: ['person@example.com'],
            Simulated: ['simulate-delivered@notification.canada.ca', 'simulate-delivered-2@notification.canada.ca', 'simulate-delivered-3@notification.canada.ca']
        },
        ReplyTos: {
            Default: '24e5288d-8bfa-4ad4-93aa-592c11a694cd',
            Second: '797865c4-788b-4184-91ae-8e45eb07e40b'
        }
    },
};

// choose which config to use here
const ConfigToUse = config.STAGING;
export default ConfigToUse;
Cypress.config('baseUrl', ConfigToUse.API.HostName);
