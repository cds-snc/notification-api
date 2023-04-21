const { recurse } = require('cypress-recurse')


// Parts of the page a user can interact with
let Components = {
    EmailAddress: () => cy.get('#email_address'),
    Password: () => cy.get('#password'),
    SubmitButton: () => cy.get('button[type="submit"]'),
    TwoFactorCode: () => cy.get('#two_factor_code'),
};

// Actions users can take on the page
let Actions = {
    EnterCode: (code) => {
        Components.TwoFactorCode().type(code);
        Components.SubmitButton().click();
    },
    Login: (email, password) => {
        // login with username and password
        cy.visit(LoginPage.URL);
        Components.EmailAddress().type(email);
        Components.Password().type(password);
        Components.SubmitButton().click();

        // get email 2fa code
        recurse(
            () => cy.task('getLastEmail', {} ), // Cypress commands to retry
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

        // ensure code is received and enter it
        cy.contains('p', "security code to log in").should('be.visible');
        cy.contains('p', 'security code to log in').invoke('text').as('MFACode');
        cy.get('@MFACode').then((text) => {
            let code = text.slice(0, 5);
            cy.visit('/two-factor-email-sent');
            Actions.EnterCode(code);
        });
    }
};

let LoginPage = {
    URL: '/sign-in', // URL for the page, relative to the base URL
    Components,
    ...Actions
};

export default LoginPage;
