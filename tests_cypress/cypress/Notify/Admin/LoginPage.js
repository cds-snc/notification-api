// Parts of the page a user can interact with
let Components = {
    EmailAddress: () => cy.get('#email_address'),
    Password: () => cy.get('#password'),
    SubmitButton: () => cy.get('button[type="submit"]'),
};

// Actions users can take on the page
let Actions = {
    Login: (email, password) => {
        Components.EmailAddress().type(email);
        Components.Password().type(password);
        Components.SubmitButton().click();
    }
};

let LoginPage = {
    URL: '/sign-in', // URL for the page, relative to the base URL
    Components,
    ...Actions
};

export default LoginPage;
