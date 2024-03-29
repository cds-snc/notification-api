/// <reference types="cypress" />

import config from '../../../config';
import Notify from "../../Notify/NotifyAPI";

describe('SRE Tools', () => {
    it('can revoke an API key using SRE auth', () => {
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
    it('cannot revoke an API key using admin auth', () => {
        Notify.API.RevokeAPIKeyWithAdminAuth({
            token: "fake-key",
            type: 'normal',
            url:'https://example.com',
            source: 'Cypress Test',
            failOnStatusCode: false
        }).as('revokeRequest');

        cy.get('@revokeRequest').then(response => {
          expect(response.status).to.eq(401);
        });
    });
});
