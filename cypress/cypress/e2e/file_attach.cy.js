/// <reference types="cypress" />

import config from '../../config';
import Notify from "../support/NotifyAPI";

describe('File attachment test', () => {
  it('can send single attachment', () => {
    cy.fixture('payloads/file_attachment_1').then(file_payload => {
      Notify.API.SendEmail({
        api_key: Cypress.env('API_KEY_LIVE'),
        to: 'andrew.leith@cds-snc.ca',
        template_id: config.templates.FILE_ATTACH_TEMPLATE_ID,
        personalisation: file_payload,
        failOnStatusCode: false
      }).as('fileRequest');

      cy.get('@fileRequest').then(todos => {
        expect(todos.status).to.eq(201);
      });
    });
  });

  it('can send 10 attachments', () => {
    cy.fixture('payloads/file_attachment_10').then(file_payload => {
      Notify.API.SendEmail({
        api_key: Cypress.env('API_KEY_LIVE'),
        to: 'andrew.leith@cds-snc.ca',
        template_id: config.templates.FILE_ATTACH_TEMPLATE_ID,
        personalisation: file_payload,
        failOnStatusCode: false
      }).as('fileRequest');

      cy.get('@fileRequest').then(todos => {
        expect(todos.status).to.eq(201);
      });
    });
  });

  it('cannot send 16 attachments', () => {
    cy.fixture('payloads/file_attachment_16').then(file_payload => {

      Notify.API.SendEmail({
        api_key: Cypress.env('API_KEY_LIVE'),
        to: 'andrew.leith@cds-snc.ca',
        template_id: config.templates.FILE_ATTACH_TEMPLATE_ID,
        personalisation: file_payload,
        failOnStatusCode: false
      }).as('fileRequest');

      cy.get('@fileRequest').then(todos => {
        expect(todos.status).to.eq(400);
      });
    });
  });

});
