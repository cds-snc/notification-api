import { LoginPage, TwoFactorPage } from '../Pages/all';
import { recurse } from 'cypress-recurse';

export default (email, password) => {
    cy.viewport(1250, 1200);

    cy.task('deleteAllEmails'); // purge email inbox to make getting the 2fa code easier

    LoginPage.Login(email, password);

    // anti-pattern, but if we wait here briefly we are much more likely to get the email on the first try
    cy.wait(2000);
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
        });

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
}
