/// <reference types="cypress" />
import config from "../../../config";
import { LoginPage, TwoFactorPage } from "../../Notify/Admin/Pages";

const { recurse } = require('cypress-recurse')

const ADMIN_COOKIE = 'notify_admin_session';


describe("Create servce and lower limit", () => {
    // Login to notify before the test suite starts
    before(() => {
        cy.viewport(1250, 1200);
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
                delay: 2000, // wait 5 seconds between attempts
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


        // Create and configure new service
        cy.visit("/accounts");

        // Click add service
        cy.get("a[href='/add-service'").click();
        cy.location("href").should("contain", "/add-service");
        // Click next
        cy.get('button[type="submit"]').click();
        // Enter service name
        cy.get("#name").click();
        cy.get("#name").type("SMSTestingService2");
        // enter sernding name
        cy.get("#email_from").click();
        cy.get("#email_from").type("smstestingservice2");
        // Submit
        cy.get('button[type="submit"]').click();

        // Return to dashboard
        cy.contains('h1', 'Dashboard').should('be.visible');

        // Go to service settings
        cy.get("a[href$='/service-settings'").last().click();
        cy.contains('h1', 'Settings').should('be.visible');

        // set default org
        cy.get("a[href$='/link-service-to-organisation'").click();
        cy.contains('h1', 'Link service to organisation').should('be.visible');
        cy.get("#organisations-0").click();
        // Submit
        cy.get('button[type="submit"]').click();

        // turn service live
        cy.get("a[href$='service-settings/switch-live'").click();
        cy.contains('h1', 'Make service live').should('be.visible');
        cy.get("#enabled-0").click();
        // Submit
        cy.get('button[type="submit"]').click();

        // reduce fragment limit
        cy.get("a[href$='/service-settings/set-sms-message-limit'").click();
        cy.get('h1').should('be.visible');
        cy.get("#message_limit").type('{selectall}').type('{backspace}').type('10')
        // Submit
        cy.get('button[type="submit"]').click();

        // Return to dashboard
        cy.contains('h1', 'Settings').should('be.visible');

        // Save service ID for subsequent tests
        cy.get("a[href^='/platform-admin/live-services'").last().invoke('attr', 'href').then(href => {
            const SERVICE_ID = href.split('?service_id=').pop();
            cy.wrap(SERVICE_ID).as('SERVICE_ID');
        });

        // cy.get('http://localhost:6012/platform-admin/live-services?service_id=79890397-c7bc-497b-85bc-d6712941d0c3
        cy.get('@SERVICE_ID').then((svcid) => {
            cy.log('SVCID: ' + svcid);
        });

    });

    it("tests Create servce and lower limit", () => {
        cy.get('@SERVICE_ID').then((svcid) => {
            cy.visit("/services/" + svcid);
        });
    });
});
