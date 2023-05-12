/// <reference types="cypress" />

const { recurse } = require('cypress-recurse')
const nodemailer = require("nodemailer");
import config from '../../../config';
import Notify from "../../Notify/NotifyAPI";

describe('Email smoke test', () => {
    before(() => {
        Cypress.config('baseUrl', config.API.HostName); // use hostname for this environment
    });

    it('can send and receive test email', () => {
    // create an ethereal email account to use for this test
    cy.task('createEmailAccount').then(acct => {
        cy.log("Email account created for test: " + acct.user);

        // send an email using the Notify API
        Notify.API.SendEmail({
            api_key: Cypress.env('API_KEY_LIVE'),
            to: acct.user, //Cypress.env('UI_TEST_USER'),
            template_id: config.Templates.SMOKE_TEST,
            personalisation: {},
        }).as('emailRequest');

        // ensure API returns a 201
        cy.get('@emailRequest').then(resp => {
            expect(resp.status).to.eq(201);
        });
        
        // verify email receipt
        recurse(
            () => cy.task('fetchEmail', acct), // Cypress commands to retry
            Cypress._.isObject, // keep retrying until the tas`k returns an object
            {
                timeout: 60000, // retry up to 1 minute
                delay: 5000, // wait 5 seconds between attempts
            },
        )
            .its('html')
            .then((html) => {
                cy.document({ log: false }).invoke({ log: false }, 'write', html)
            })

        // ensure SMOKE test email is received
        cy.contains('p', "SMOKE_TEST").should('be.visible');
    });
    });
});

