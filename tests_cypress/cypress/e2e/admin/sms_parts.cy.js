/// <reference types="cypress" />
import config from "../../../config";
import App from "../../Notify/Admin/app";

describe("Create servce and lower limit", () => {
    // Login to notify before the test suite starts
    before(() => {
        // some global test settings
        const ADMIN_COOKIE = 'notify_admin_session';
        Cypress.config('baseUrl', config.Admin.HostName); // use hostname for this environment
        cy.clearCookie(ADMIN_COOKIE); // clear auth cookie

        // We'll use two app flows to to setup our tests
        App.Flows.Login(config.Admin.AdminUser, Cypress.env('ADMIN_USER_PASSWORD'));
        App.Flows.CreateService("SMS Test Service");

        // set default org, turn service live, reduce fragment limit
        SetDefaultSettings();

        // Save service ID for subsequent tests (older article that explains what is being done here: https://www.stevenhicks.me/blog/2020/02/working-with-variables-in-cypress-tests/)
        cy.get("a[href^='/platform-admin/live-services'").last().invoke('attr', 'href').then(href => {
            const SERVICE_ID = href.split('?service_id=').pop();
            cy.wrap(SERVICE_ID).as('SERVICE_ID');
        });
    });

    it("tests Create servce and lower limit", () => {
        // the 
        cy.get('@SERVICE_ID').then((svcid) => {
            cy.visit("/services/" + svcid);
        });
    });
});

// TODO: move this to a common file; maybe a flow but it seems too specific
function SetDefaultSettings() {
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
}