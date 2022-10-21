// Parts of the page a user can interact with
let Components = {
    TwoFactorCode: () => cy.get('#two_factor_code'),
    ContinueButton: () => cy.get('button[type="submit"]'),
};

// Actions users can take on the page
let Actions = {
    EnterCode: (code) => {
        Components.TwoFactorCode().type(code);
        Components.ContinueButton().click();
    }
};

let TwoFactorPage = {
    URL: '/two-factor-email-sent', // URL for the page, relative to the base URL
    Components,
    ...Actions
};

export default TwoFactorPage;
