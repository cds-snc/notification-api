import jwt from "jsonwebtoken";
import config from "../../config";

const Utilities = {
    CreateJWT: () => {
        const claims = {
            'iss': Cypress.env('ADMIN_USERNAME'),
            'iat': Math.round(Date.now() / 1000)
        }

        var token = jwt.sign(claims, Cypress.env('ADMIN_SECRET'));

        return token;
    },
};
const Admin = {
    SendOneOff: ({to, template_id}) => {

        var token = Utilities.CreateJWT();
        return cy.request({
            url: `/service/${config.Services.Cypress}/send-notification`,
            method: 'POST',
            headers: {
                Authorization: `Bearer ${token}`,
            },
            body: {
                'to': to,
                'template_id': template_id,
                'created_by': Cypress.env('NOTIFY_USER_ID'),
            }
        });
    }
}
// const Admin = {
//     CreateService: () => {
//         var token = Utilities.CreateJWT();
//         cy.request({
//             url: '/service',
//             method: 'POST',
//             headers: {
//                 Authorization: `Bearer ${token}`,
//             },
//             body: {
//                 'created_by': 'c7aa883e-3130-4031-8610-bbe22719b23e',
//                 'name': 'Testing Service',
//                 'organisation_type': 'central',
//                 'active': true,
//                 'message_limit': 50,
//                 'user_id': 'c7aa883e-3130-4031-8610-bbe22719b23e',
//                 'restricted': true,
//                 'email_from': 'testing_service23',
//                 'default_branding_is_french': false,
//                 'sms_daily_limit': 1000
//             }
//         }).as('createRequest');

//         var service_data;
//         cy.get('@createRequest').then((resp) => {
//             service_data = resp.body.data;
//             console.log('sd', resp);
//             cy.wrap(service_data).as('service_data');
//             cy.request({
//                 url: `/service/${resp.body.data.id}/billing/free-sms-fragment-limit`,
//                 method: 'POST',
//                 headers: {
//                     Authorization: `Bearer ${token}`,
//                 },
//                 body: {
//                     "financial_year_start": null,
//                     "free_sms_fragment_limit": 25_000,
//                 }
//             });
//         });


//     },
//     ArchiveService: (service_id) => {
//         var token = Utilities.CreateJWT();
//         cy.request({
//             url: `/service/${service_id}/archive`,
//             method: 'POST',
//             headers: {
//                 Authorization: `Bearer ${token}`,
//             }
//         });
//     },
//     Settings: {
//         SetDailyLimit: (service_id, limit) => {
//             var token = Utilities.CreateJWT();
//             cy.request({
//                 url: `/service/${service_id}`,
//                 method: 'POST',
//                 headers: {
//                     Authorization: `Bearer ${token}`,
//                 },
//                 body: {
//                     sms_daily_limit: limit
//                 }
//             });

//         }
//     }
// }

const API = {
    SendEmail: ({ api_key, to, template_id, personalisation, failOnStatusCode = true, email_reply_to_id }) => {
        return cy.request({
            failOnStatusCode: failOnStatusCode,
            url: '/v2/notifications/email',
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                Authorization: 'ApiKey-v1 ' + api_key,
            },
            body: {
                "email_address": to,
                "template_id": template_id,
                "personalisation": personalisation,
                ...(email_reply_to_id) && { email_reply_to_id: email_reply_to_id } // only add email_reply_to_id if it's defined
            }
        });
    },
    SendBulkEmail: ({ api_key, to, bulk_name, template_id, personalisation, failOnStatusCode = true }) => {
        return cy.request({
            failOnStatusCode: failOnStatusCode,
            url: '/v2/notifications/bulk',
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                Authorization: 'ApiKey-v1 ' + api_key,
            },
            body: {
                "name": bulk_name,
                "template_id": template_id,
                "rows": [
                    ["email address"],
                    ...to
                ],
            }
        });
    },
    SendSMS: ({ api_key, to, template_id, personalisation, failOnStatusCode = true }) => {
        return cy.request({
            failOnStatusCode: failOnStatusCode,
            url: '/v2/notifications/sms',
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                Authorization: 'ApiKey-v1 ' + api_key,
            },
            body: {
                "phone_number": to,
                "template_id": template_id,
                "personalisation": personalisation,
            }
        });
    },
    SendBulkSMS: ({ api_key, to, bulk_name, template_id, personalisation, failOnStatusCode = true }) => {
        return cy.request({
            failOnStatusCode: failOnStatusCode,
            url: '/v2/notifications/bulk',
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                Authorization: 'ApiKey-v1 ' + api_key,
            },
            body: {
                "name": bulk_name,
                "template_id": template_id,
                "rows": [
                    ["phone number"],
                    ...to
                ],
            }
        });
    },

}

export default { API, Utilities, Admin };
