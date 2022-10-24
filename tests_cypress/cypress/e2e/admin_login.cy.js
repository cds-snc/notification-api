/// <reference types="cypress" />

import config from "../../config";
import { LoginPage, TwoFactorPage } from "../Notify/Admin/Pages";

const { recurse } = require('cypress-recurse')

const ADMIN_COOKIE = 'notify_admin_session';
describe('ADMIN', () => {

    // Login to notify before the test suite starts
    before(() => {
        Cypress.config('baseUrl', config.Admin.HostName); // use hostname for this environment
        cy.clearCookie(ADMIN_COOKIE); // clear auth cookie
        cy.task('deleteAllEmails'); // purge email inbox to make getting the 2fa code easier

        cy.visit(LoginPage.URL);
        LoginPage.Login(config.Admin.AdminUser, Cypress.env('ADMIN_USER_PASSWORD'));

        // retry fetching the email 
        recurse(
            () => cy.task('getLastEmail'), // Cypress commands to retry
            Cypress._.isObject, // keep retrying until the task returns an object
            {
                timeout: 60000, // retry up to 1 minute
                delay: 5000, // wait 5 seconds between attempts
            },
        )
            .its('html')
            .then((html) => {
                cy.document({ log: false }).invoke({ log: false }, 'write', html)
            })

        // ensure the email with security code is received 
        cy.contains('p', "security code to log in").should('be.visible');

        cy.contains('p', 'security code to log in').invoke('text').as('MFACode');
        cy.get('@MFACode').then((text) => {
            let code = text.slice(0, 5);
            cy.visit(TwoFactorPage.URL);
            TwoFactorPage.EnterCode(code);
        });

        // ensure we logged in correctly
        cy.contains('h1', 'Sign-in history').should('be.visible');
    });

    // Before each test, persist the auth cookie so we don't have to login again
    beforeEach(() => {
        Cypress.Cookies.preserveOnce(ADMIN_COOKIE);

        // stop the recurring dashboard fetch requests
        cy.intercept('GET', '**/dashboard.json', {});
    });


    it('displays accounts page', () => {
        cy.visit("/accounts");
        cy.contains('h1', 'Your services').should('be.visible');
    });

    it('displays notify service page', () => {
        cy.visit(`/services/${config.Services.Notify}`);
        cy.contains('h1', 'Dashboard').should('be.visible');
    });

    it('has a qualtrics survey', () => {
        cy.get('#QSIFeedbackButton-btn').should('be.visible'); // qualtrics survey button
        cy.get('#QSIFeedbackButton-btn').click(); // click the button
        cy.get('#QSIFeedbackButton-survey-iframe').should('be.visible'); // 
    });
});