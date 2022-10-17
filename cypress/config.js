const config = {
    STAGING: {
        apiHostName: "https://api.staging.notification.cdssandbox.xyz",
        templates: {
            "FILE_ATTACH_TEMPLATE_ID": "7246c71e-3d60-458b-96af-af17a5b07659",
            "SIMPLE_EMAIL_TEMPLATE_ID": "939dafde-1b60-47f0-a6d5-c9080d92a4a8",
            "VARIABLES_EMAIL_TEMPLATE_ID": "1101a00a-11b7-4036-865c-add43fcff7c9"
        },
        users: {
            team: ['andrew.leith+bannertest@cds-snc.ca'],
            nonTeam: ['person@example.com'],
            simulated: ['simulate-delivered@notification.canada.ca', 'simulate-delivered-2@notification.canada.ca', 'simulate-delivered-3@notification.canada.ca']
        },
        replyTos: {
            default: '24e5288d-8bfa-4ad4-93aa-592c11a694cd',
            second: '797865c4-788b-4184-91ae-8e45eb07e40b'
        }
    },
    LOCAL: {
        apiHostName: "http://localhost:6011",
        templates: {
            "FILE_ATTACH_TEMPLATE_ID": "7246c71e-3d60-458b-96af-af17a5b07659",
            "SIMPLE_EMAIL_TEMPLATE_ID": "939dafde-1b60-47f0-a6d5-c9080d92a4a8",
            "VARIABLES_EMAIL_TEMPLATE_ID": "1101a00a-11b7-4036-865c-add43fcff7c9"
        },
        users: {
            team: ['andrew.leith+bannertest@cds-snc.ca'],
            nonTeam: ['person@example.com'],
            simulated: ['simulate-delivered@notification.canada.ca', 'simulate-delivered-2@notification.canada.ca', 'simulate-delivered-3@notification.canada.ca']
        },
        replyTos: {
            default: '24e5288d-8bfa-4ad4-93aa-592c11a694cd',
            second: '797865c4-788b-4184-91ae-8e45eb07e40b'
        }
    }
};

// choose which config to use here
export default config.LOCAL;
// export default config.STAGING;
