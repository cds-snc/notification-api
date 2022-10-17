/// <reference types="cypress" />

import config from '../../config';
import Notify from "../support/NotifyAPI";

describe('Email notifications test', () => {
  var keys = {
    LIVE: Cypress.env('API_KEY_LIVE'),
    TEAM: Cypress.env('API_KEY_TEAM'),
    TEST: Cypress.env('API_KEY_TEST')
  };


  for (const api_key in keys) {
    context(`With ${api_key} api key`, () => {
      it('can send email notification without personalisation', () => {
        Notify.API.SendEmail({
          api_key: keys[api_key],
          to: api_key === 'TEAM' ? config.users.team[0] : config.users.simulated[1],
          template_id: config.templates.SIMPLE_EMAIL_TEMPLATE_ID,
          personalisation: {},
        }).as('emailRequest');

        cy.get('@emailRequest').then(resp => {
          expect(resp.status).to.eq(201);
        });
      });

      it('can send email notification with personalisation', () => {
        Notify.API.SendEmail({
          api_key: keys[api_key],
          to: api_key === 'TEAM' ? config.users.team[0] : config.users.simulated[1],
          template_id: config.templates.VARIABLES_EMAIL_TEMPLATE_ID,
          personalisation: {
            name: 'Alex',
            has_stuff: true
          },
        }).as('emailRequest');

        cy.get('@emailRequest').then(resp => {
          expect(resp.status).to.eq(201);
        });

      });

      it('can send email to smoke test addresses', () => {
        for (const email of config.users.simulated) {
          Notify.API.SendEmail({
            api_key: keys[api_key],
            to: email,
            template_id: config.templates.SIMPLE_EMAIL_TEMPLATE_ID,
            personalisation: {},
          }).as('emailRequest');

          cy.get('@emailRequest').then(resp => {
            expect(resp.status).to.eq(201);
          });
        }
      });

      it('can use a non-default replyTo', () => {
        Notify.API.SendEmail({
          api_key: keys[api_key],
          to: config.users.simulated[0],
          template_id: config.templates.SIMPLE_EMAIL_TEMPLATE_ID,
          personalisation: {},
          email_reply_to_id: config.replyTos.second
        }).as('emailRequest');

        cy.get('@emailRequest').then(resp => {
          expect(resp.status).to.eq(201);
        });
      });

      it('can use a default replyTo', () => {
        Notify.API.SendEmail({
          api_key: keys[api_key],
          to: config.users.simulated[0],
          template_id: config.templates.SIMPLE_EMAIL_TEMPLATE_ID,
          personalisation: {},
          email_reply_to_id: config.replyTos.default
        }).as('emailRequest');

        cy.get('@emailRequest').then(resp => {
          expect(resp.status).to.eq(201);
        });
      });

      it('can use no replyTo', () => {
        Notify.API.SendEmail({
          api_key: keys[api_key],
          to: config.users.simulated[0],
          template_id: config.templates.SIMPLE_EMAIL_TEMPLATE_ID,
          personalisation: {}
        }).as('emailRequest');

        cy.get('@emailRequest').then(resp => {
          expect(resp.status).to.eq(201);
        });
      });
      // Additional tests for TEAM keys
      if (api_key === 'TEAM') {
        it('can send to team address', () => {
          Notify.API.SendEmail({
            api_key: keys[api_key],
            to: config.users.team[0],
            template_id: config.templates.SIMPLE_EMAIL_TEMPLATE_ID,
            personalisation: {},
          }).as('emailRequest');

          cy.get('@emailRequest').then(resp => {
            expect(resp.status).to.eq(201);
          });
        });

        it('cannot send to non-team address', () => {
          Notify.API.SendEmail({
            api_key: keys[api_key],
            to: config.users.nonTeam[0],
            template_id: config.templates.SIMPLE_EMAIL_TEMPLATE_ID,
            personalisation: {},
            failOnStatusCode: false
          }).as('emailRequest');

          cy.get('@emailRequest').then(resp => {
            expect(resp.status).to.eq(400);
          });
        });
      }
    });
  }
});

