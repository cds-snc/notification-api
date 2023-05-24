// Parts of the page a user can interact with
let Components = {
    YesAddRecipients: () => cy.contains('a', 'Yes, add recipients').first(),
};

// Actions users can take on the page
let Actions = {
    SelectTemplate: (template_name) => {
        cy.contains('a', template_name).first().click();
        //cy.contains('h1', 'SMOKE_TEST_EMAIL').should('be.visible');
    },
    GotoAddRecipients: () => {
        Components.YesAddRecipients().click();
        //cy.contains('h1', 'Add recipients').should('be.visible');
    }
};

let TemplatesPage = {
    Components,
    ...Actions
};

export default TemplatesPage;
