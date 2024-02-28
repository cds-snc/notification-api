import jwt from "jsonwebtoken";
import config from "../../config";

const Utilities = {
    CreateJWT: (user, secret) => {
        const claims = {
            'iss': user,
            'iat': Math.round(Date.now() / 1000)
        }

        var token = jwt.sign(claims, secret);

        return token;
    },
    GenerateID: (length=10) => {
        let result = '';
        const characters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
        const charactersLength = characters.length;
        let counter = 0;
        while (counter < length) {
            result += characters.charAt(Math.floor(Math.random() * charactersLength));
            counter += 1;
        }
        return result;
    }
};
const Admin = {
    SendOneOff: ({to, template_id}) => {
        var token = Utilities.CreateJWT(Cypress.env('ADMIN_USERNAME'), Cypress.env(config.CONFIG_NAME).ADMIN_SECRET);
        return cy.request({
            url: `/service/${config.Services.Cypress}/send-notification`,
            method: 'POST',
            headers: {
                Authorization: `Bearer ${token}`,
            },
            body: {
                'to': to,
                'template_id': template_id,
                'created_by': Cypress.env(config.CONFIG_NAME).NOTIFY_USER_ID,
            }
        });
    }
}

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
    SendBulkEmail: ({ api_key, to, bulk_name, template_id, personalisation, failOnStatusCode = true, scheduled_for}) => {
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
                ...(scheduled_for) && { scheduled_for: scheduled_for } // only add scheduled_for if it's defined
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
    CreateAPIKey: ({ service_id, key_type, name }) => {
        var token = Utilities.CreateJWT(Cypress.env('ADMIN_USERNAME'), Cypress.env(config.CONFIG_NAME).ADMIN_SECRET);
        return cy.request({
            url: `/service/${service_id}/api-key`,
            method: 'POST',
            headers: {
                Authorization: `Bearer ${token}`,
            },
            body: {
                key_type: key_type,
                name: name,
                created_by: Cypress.env(config.CONFIG_NAME).NOTIFY_USER_ID,
            }
        });
    },
    RevokeAPIKey: ({ token, type, url, source, failOnStatusCode = true }) => {
        
        var jwt_token = Utilities.CreateJWT(Cypress.env('SRE_USERNAME'), Cypress.env(config.CONFIG_NAME).SRE_SECRET);
        cy.request({
            url: `/sre-tools/api-key-revoke`,
            method: 'POST',
            headers: {
                Authorization: `Bearer ${jwt_token}`,
            },
            body: {
                "token": token,
                "type": type,
                "url": url,
                "source": source
            }
        });
    },
    RevokeAPIKeyWithAdminAuth: ({ token, type, url, source, failOnStatusCode = true }) => {
        var jwt_token = Utilities.CreateJWT(Cypress.env('ADMIN_USERNAME'),Cypress.env(config.CONFIG_NAME).ADMIN_SECRET);
        return cy.request({
            url: `/sre-tools/api-key-revoke`,
            method: 'POST',
            headers: {
                Authorization: `Bearer ${jwt_token}`,
            },
            body: {
                "token": token,
                "type": type,
                "url": url,
                "source": source
            },
            failOnStatusCode: failOnStatusCode
        });
    }

}

export default { API, Utilities, Admin };
