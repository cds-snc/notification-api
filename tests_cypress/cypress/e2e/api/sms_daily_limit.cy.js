/// <reference types="cypress" />

import config from "../../../config";
import Notify from "../../Notify/NotifyAPI";

var service;

describe('SMS Daily limit', () => {
    before(() => {
        Cypress.config('baseUrl', config.Hostnames.API); // use hostname for this environment
    });
    
    before(() => {
        Notify.Admin.CreateService();
        cy.pause();
        cy.get('@service_data').then((Service) => {
            service = Service; // save this for the after hook (this is an anti-pattern though)
            Notify.Admin.Settings.SetDailyLimit(Service.id, 2);
        });
    });

    after(() => {
        Notify.Admin.ArchiveService(service.id);
    });

    context('one-off API sends', () => {
        it('blocks single-fragment SMS when limit has been reached', () => {
            Notify.API.SendEmail({
                api_key: Cypress.env('API_KEY_LIVE'),
                to: 'andrew.leith@cds-snc.ca',
                template_id: config.Templates.SIMPLE_EMAIL_TEMPLATE_ID,
                failOnStatusCode: true
            }).as('notificationRequest1');
            cy.get('@notificationRequest1').then(todos => {
                expect(todos.status).to.eq(201);
            });

            Notify.API.SendEmail({
                api_key: Cypress.env('API_KEY_LIVE'),
                to: 'andrew.leith@cds-snc.ca',
                template_id: config.templates.SIMPLE_EMAIL_TEMPLATE_ID,
                failOnStatusCode: true
            }).as('notificationRequest2');
            cy.get('@notificationRequest2').then(todos => {
                expect(todos.status).to.eq(201);
            });

            Notify.API.SendEmail({
                api_key: Cypress.env('API_KEY_LIVE'),
                to: 'andrew.leith@cds-snc.ca',
                template_id: config.templates.SIMPLE_EMAIL_TEMPLATE_ID,
                failOnStatusCode: false
            }).as('notificationRequest3');
            cy.get('@notificationRequest2').then(todos => {
                expect(todos.status).to.eq(400);
            });
        });

        it('blocks multi-fragment SMS when limit has been reached');

        it('blocks multi-fragment SMS before limit has been reached');
    });

    context('bulk API sends', () => {
        it('blocks single-fragment SMS when limit has been reached');

        it('blocks multi-fragment SMS when limit has been reached');

        it('blocks multi-fragment SMS before limit has been reached');
    });
});