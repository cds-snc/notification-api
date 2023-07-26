/// <reference types="cypress" />

import config from "../../../config";
import { LoginPage } from "../../Notify/Admin/Pages/all";

const { recurse } = require('cypress-recurse')

const ADMIN_COOKIE = 'notify_admin_session3';
describe('Qualtrics', () => {

    // Login to notify before the test suite starts
    before(() => {
        Cypress.config('baseUrl', config.Hostnames.Admin); // use hostname for this environment
        LoginPage.Login(Cypress.env('NOTIFY_USER'), Cypress.env('NOTIFY_PASSWORD'));
    });

    // Before each test, persist the auth cookie so we don't have to login again
    beforeEach(() => {
        // stop the recurring dashboard fetch requests
        cy.intercept('GET', '**/dashboard.json', {});
    });

    it('survey button appears and survey opens', () => {
        cy.visit(`/services/${config.Services.Notify}`);
        cy.contains('h1', 'Dashboard').should('be.visible');
        cy.get('#QSIFeedbackButton-btn').should('be.visible'); // qualtrics survey button
        cy.get('#QSIFeedbackButton-btn').click(); // click the button
        cy.get('#QSIFeedbackButton-survey-iframe').should('be.visible'); // 
    });
});