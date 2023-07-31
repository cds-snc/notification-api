/// <reference types="cypress" />

const { recurse } = require('cypress-recurse')
const nodemailer = require("nodemailer");
import config from '../../../config';
import Notify from "../../Notify/NotifyAPI";

const ADMIN_COOKIE = 'notify_admin_session';

describe(`Smoke tests [${config.CONFIG_NAME}]`, () => {
    context('API tests', () => {
        context('Email', () => {
            it('can send/receive a one-off email', () => {
                // create an ethereal email account to use for this test
                cy.task('createEmailAccount').then(acct => {
                    cy.log("Email account created for test: " + acct.user);

                    // send an email using the Notify API
                    Notify.API.SendEmail({
                        api_key: Cypress.env(config.CONFIG_NAME).API_KEY_LIVE,
                        to: acct.user,
                        template_id: config.Templates.SMOKE_TEST_EMAIL,
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
                            log: true,
                            limit: 50, // max number of iterations
                            timeout: 30000, // time limit in ms
                            delay: 500, // delay before next iteration, ms
                        },
                    ).then(response => {
                        response.html = `
                            <div style="max-width: 580px; margin: 0px auto">
                                <ul>
                                    <li><strong>FROM:</strong> ${response.from}</li>
                                    <li><strong>TO:</strong> ${response.to}</li>    
                                    <li><strong>SUBJECT:</strong> ${response.subject}</li>
                                </ul>
                                <hr />
                            </div>
                        ` + response.html;
                        cy.document().then((document) => { document.documentElement.innerHTML = response.html })
                    });

                    // ensure SMOKE test email is received
                    cy.contains('p', "SMOKE_TEST").should('be.visible');
                });
            });

            it('can send/receive bulk CSV emails', () => {
                // create an ethereal email account to use for this test
                cy.task('createEmailAccount').then(acct => {
                    cy.log("Email account created for test: " + acct.user);

                    // send an email using the Notify API
                    Notify.API.SendBulkEmail({
                        api_key: Cypress.env(config.CONFIG_NAME).API_KEY_LIVE,
                        to: [[acct.user],[acct.user],[acct.user],[acct.user],[acct.user]],
                        bulk_name: "Smoke Test",
                        template_id: config.Templates.SMOKE_TEST_EMAIL_BULK,
                        personalisation: {},
                    }).as('emailRequest');

                    // ensure API returns a 201
                    cy.get('@emailRequest').then(resp => {
                        expect(resp.status).to.eq(201);
                    });
                    
                    // verify email receipt
                    recurse(
                        () => cy.task('fetchEmail', acct), // Cypress commands to retry
                        (response) => response.totalEmails === 5, // keep trying until the inbox has 5 emails
                        {
                            log: true,
                            limit: 50, // max number of iterations
                            timeout: 30000, // time limit in ms
                            delay: 500, // delay before next iteration, ms
                        },
                    ).then(response => {
                        cy.document().then((document) => { document.documentElement.innerHTML = response.html })
                    });
                    // ensure SMOKE test email is received
                    cy.contains('p', "SMOKE_TEST_EMAIL_BULK").should('be.visible');
                });
                
            });

            it('can send/receive a one-off email w/ attachment', () => {
                cy.task('createEmailAccount').then(acct => {
                    cy.log("Email account created for test: " + acct.user);
    
                    // send an email using the Notify API
                    cy.fixture('payloads/file_attachment_1').then(file_payload => {
                        Notify.API.SendEmail({
                          api_key: Cypress.env(config.CONFIG_NAME).API_KEY_LIVE,
                          to: acct.user,
                          template_id: config.Templates.SMOKE_TEST_EMAIL_ATTACH,
                          personalisation: file_payload,
                          failOnStatusCode: false
                        }).as('fileRequest');
                  
                        cy.get('@fileRequest').then(todos => {
                          expect(todos.status).to.eq(201);
                        });
                    
                        // verify email receipt
                        recurse(
                            () => cy.task('fetchEmail', acct), // Cypress commands to retry
                            Cypress._.isObject, // keep retrying until the tas`k returns an object
                            {
                                log: true,
                                limit: 50, // max number of iterations
                                timeout: 30000, // time limit in ms
                                delay: 500, // delay before next iteration, ms
                            },
                        ).then(response => {
                            expect(response.attachments[0].filename).to.equal(file_payload.application_file1.filename);
                             cy.document().then((document) => { document.documentElement.innerHTML = response.html })
                        });
                    });
                    // ensure SMOKE test email is received
                    cy.contains('p', "SMOKE_TEST_EMAIL_ATTACH").should('be.visible');
                });
            });

            it('can send/receive one-off emails w/ link attachment', () => {
                cy.task('createEmailAccount').then(acct => {
                    cy.log("Email account created for test: " + acct.user);
    
                    // send an email using the Notify API
                    cy.fixture('payloads/file_link').then(file_payload => {
                        Notify.API.SendEmail({
                          api_key: Cypress.env(config.CONFIG_NAME).API_KEY_LIVE,
                          to: acct.user,
                          template_id: config.Templates.SMOKE_TEST_EMAIL_LINK,
                          personalisation: file_payload,
                          failOnStatusCode: false
                        }).as('fileRequest');
                  
                        cy.get('@fileRequest').then(todos => {
                          expect(todos.status).to.eq(201);
                        });
                    
                        // verify email receipt
                        recurse(
                            () => cy.task('fetchEmail', acct), // Cypress commands to retry
                            Cypress._.isObject, // keep retrying until the tas`k returns an object
                            {
                                log: true,
                                limit: 50, // max number of iterations
                                timeout: 30000, // time limit in ms
                                delay: 500, // delay before next iteration, ms
                            },
                        ).then(response => {
                             cy.document().then((document) => { document.documentElement.innerHTML = response.html })
                        });
                    });
                    // ensure SMOKE test email is received
                    cy.contains('p', "SMOKE_TEST_EMAIL_LINK").should('be.visible');
                    // ensure link to ddapi is in the email
                    cy.contains('p', config.Hostnames.DDAPI).should('be.visible');
                });
            });

            it('can schedule and receive bulk CSV emails', () => {
                // create an ethereal email account to use for this test
                cy.task('createEmailAccount').then(acct => {
                    cy.log("Email account created for test: " + acct.user);

                    // Schedule 20 seconds from now
                    var secheduled_for = new Date(); 
                    secheduled_for.setSeconds(secheduled_for.getSeconds()+20);
 
                    // send an email using the Notify API
                    Notify.API.SendBulkEmail({
                        api_key: Cypress.env(config.CONFIG_NAME).API_KEY_LIVE,
                        to: [[acct.user],[acct.user],[acct.user],[acct.user],[acct.user]],
                        bulk_name: "Smoke Test",
                        template_id: config.Templates.SMOKE_TEST_EMAIL_BULK,
                        personalisation: {},
                        scheduled_for: secheduled_for.toISOString(),
                    }).as('emailRequest');

                    // ensure API returns a 201
                    cy.get('@emailRequest').then(resp => {
                        expect(resp.status).to.eq(201);
                    });
                    
                    // verify email receipt
                    recurse(
                        () => cy.task('fetchEmail', acct), // Cypress commands to retry
                        (response) => response.totalEmails === 5, // keep trying until the inbox has 5 emails
                        {
                            log: true,
                            limit: 50, // max number of iterations
                            timeout: 65000, // time limit in ms
                            delay: 500, // delay before next iteration, ms
                        },
                    ).then(response => {
                        cy.document().then((document) => { document.documentElement.innerHTML = response.html })
                    });
                    // ensure SMOKE test email is received
                    cy.contains('p', "SMOKE_TEST_EMAIL_BULK").should('be.visible');
                });
                
            });
        });

        context('SMS', () => {
            it('can send a one-off SMS', () => {
                // send an email using the Notify API
                Notify.API.SendSMS({
                    api_key: Cypress.env(config.CONFIG_NAME).API_KEY_LIVE,
                    to: config.Users.SimulatedPhone[0],
                    template_id: config.Templates.SMOKE_TEST_SMS,
                    personalisation: {},
                }).as('emailRequest');

                // ensure API returns a 201
                cy.get('@emailRequest').then(resp => {
                    expect(resp.status).to.eq(201);
                });
            });
            it('can send bulk CSV SMSs', () => {
                // send an email using the Notify API
                Notify.API.SendBulkSMS({
                    bulk_name: "Smoke Test",
                    api_key: Cypress.env(config.CONFIG_NAME).API_KEY_LIVE,
                    to: [[config.Users.SimulatedPhone[0]],[config.Users.SimulatedPhone[1]]],
                    template_id: config.Templates.SMOKE_TEST_SMS,
                    personalisation: {},
                }).as('emailRequest');

                // ensure API returns a 201
                cy.get('@emailRequest').then(resp => {
                    expect(resp.status).to.eq(201);
                });
            });
        });
    });

    context('ADMIN tests', () => {
        context('Email', () => {
            it('can send/receive a one-off email', () => {
                // create an ethereal email account to use for this test
                cy.task('createEmailAccount').then(acct => {
                    cy.log("Email account created for test: " + acct.user);

                    Notify.Admin.SendOneOff({
                        to: acct.user, 
                        template_id: config.Templates.SMOKE_TEST_EMAIL
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
                            log: true,
                            limit: 50, // max number of iterations
                            timeout: 30000, // time limit in ms
                            delay: 500, // delay before next iteration, ms
                        },
                    ).then(response => {
                        response.html = `
                            <div style="max-width: 580px; margin: 0px auto">
                                <ul>
                                    <li><strong>FROM:</strong> ${response.from}</li>
                                    <li><strong>TO:</strong> ${response.to}</li>    
                                    <li><strong>SUBJECT:</strong> ${response.subject}</li>
                                </ul>
                                <hr />
                            </div>
                        ` + response.html;
                        cy.document().then((document) => { document.documentElement.innerHTML = response.html })
                    });

                    // ensure SMOKE test email is received
                    cy.contains('p', "SMOKE_TEST").should('be.visible');
                });
                
            });
            // it('can send/receive bulk CSV emails', () => {
            // });
        });
        
        context('SMS', () => {
            // it('can send a one-off SMS', () => {
            // });
            // it('can send bulk CSV SMSs', () => {
            // });
        });
    });

});

