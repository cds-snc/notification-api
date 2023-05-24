// Parts of the page a user can interact with
let Components = {
    SendType: () => cy.get('#what_type-1'),
    Recipient: () => cy.get('#placeholder_value'),
    ContinueButton: () => cy.contains('button', 'Continue'),
    SendButton: () => cy.contains('button', 'Send 1 email'),
};

// Actions users can take on the page
let Actions = {
    SendOneOffEmail: (to) => {
        Components.SendType().check('one_recipient');
        Components.Recipient().type(to);
        Components.ContinueButton().click();
        Components.SendButton().click();
    }
};

let AddRecipientsPage = {
    Components,
    ...Actions
};

export default AddRecipientsPage;
