let STAGING = {
    API: {
        HostName: 'https://api.staging.notification.cdssandbox.xyz',
    },
    Admin: {
        HostName: 'https://staging.notification.cdssandbox.xyz',
    },
    DDAPI: {
        HostName: 'https://api.document.staging.notification.cdssandbox.xyz'
    },
    Services: {
        Notify: 'd6aa2c68-a2d9-4437-ab19-3ae8eb202553',
        Cypress: '5c8a0501-2aa8-433a-ba51-cefb8063ab93'
    },
    Templates: {
        'FILE_ATTACH_TEMPLATE_ID': '7246c71e-3d60-458b-96af-af17a5b07659',
        'SIMPLE_EMAIL_TEMPLATE_ID': '939dafde-1b60-47f0-a6d5-c9080d92a4a8',
        'VARIABLES_EMAIL_TEMPLATE_ID': '1101a00a-11b7-4036-865c-add43fcff7c9',
        'SMOKE_TEST_EMAIL': '5e26fae6-3565-44d5-bfed-b18680b6bd39',
        'SMOKE_TEST_EMAIL_BULK': '04145882-0f21-4d57-940d-69883fc23e77',
        'SMOKE_TEST_EMAIL_ATTACH': 'bf85def8-01b4-4c72-98a8-86f2bc10f2a4',
        'SMOKE_TEST_EMAIL_LINK': '37924e87-038d-48b8-b122-f6dddefd56d5',
        'SMOKE_TEST_SMS': '16cae0b3-1d44-47ad-a537-fd12cc0646b6'
        
    },
    Users: {
        Team: ['andrew.leith+bannertest@cds-snc.ca'],
        NonTeam: ['person@example.com'],
        Simulated: ['success@simulator.amazonses.com', 'simulate-delivered-2@notification.canada.ca', 'simulate-delivered-3@notification.canada.ca'],
        SimulatedPhone: ['+16132532222', '+16132532223', '+16132532224']
    },
    ReplyTos: {
        Default: '24e5288d-8bfa-4ad4-93aa-592c11a694cd',
        Second: '797865c4-788b-4184-91ae-8e45eb07e40b'
    },
    viewports: [320,375,640,768]
};

let LOCAL = {
    API: {
        HostName: 'http://localhost:6011',
    },
    Admin: {
        HostName: 'http://localhost:6012',
    },
    Templates: {
        'FILE_ATTACH_TEMPLATE_ID': '7246c71e-3d60-458b-96af-af17a5b07659',
        'SIMPLE_EMAIL_TEMPLATE_ID': '939dafde-1b60-47f0-a6d5-c9080d92a4a8',
        'VARIABLES_EMAIL_TEMPLATE_ID': '1101a00a-11b7-4036-865c-add43fcff7c9'
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
};

const config = {
    STAGING,
    LOCAL,
};

// choose which config to use here
const ConfigToUse = config.STAGING;

export default ConfigToUse;
