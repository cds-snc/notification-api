/// <reference types="cypress" />

import config from "../../../config";
import { LoginPage } from "../../Notify/Admin/Pages/all";


const ADMIN_COOKIE = 'notify_admin_session';
describe('Basic login', () => {

    // Login to notify before the test suite starts
    before(() => {
        Cypress.config('baseUrl', config.Hostnames.Admin); // use hostname for this environment

        LoginPage.Login(Cypress.env('NOTIFY_USER'), Cypress.env('NOTIFY_PASSWORD'));

        // ensure we logged in correctly
        cy.contains('h1', 'Sign-in history').should('be.visible');
    });

    // Before each test, persist the auth cookie so we don't have to login again
    beforeEach(() => {
        // stop the recurring dashboard fetch requests
        cy.intercept('GET', '**/dashboard.json', {});
    });

    it('succeeds and ADMIN displays accounts page', () => {
        cy.visit("/accounts");

        cy.injectAxe();
        cy.checkA11y();
        cy.contains('h1', 'Your services').should('be.visible');
    });

    it('displays notify service page', () => {
        cy.visit(`/services/${config.Services.Notify}`);
        cy.contains('h1', 'Dashboard').should('be.visible');
    });
});