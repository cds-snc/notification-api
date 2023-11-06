/// <reference types="cypress" />

import config from '../../../config';
import Notify from "../../Notify/NotifyAPI";

describe('SRE Tools', () => {
    it('can revoke an API key', () => {
        let key_name = 'api-revoke-test-' + Notify.Utilities.GenerateID();

        Notify.API.CreateAPIKey({
            service_id: config.Services.Cypress,
            key_type: 'normal',
            name: key_name
        }).as('APIKey');

        cy.log("Generated API KEY: " + key_name);

        cy.get('@APIKey').then((response) => {
            let api_key = response.body.data.key_name + "-" + config.Services.Cypress + "-" + response.body.data.key;

            Notify.API.RevokeAPIKey({
                token: api_key,
                type: 'normal',
                url:'https://example.com',
                source: 'Cypress Test'
            });
            cy.log("Revoked API KEY: " + key_name);
        });
    });
});
