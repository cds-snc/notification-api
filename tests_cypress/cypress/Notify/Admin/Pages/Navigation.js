// Parts of the page a user can interact with
let Components = {};

// Actions users can take on the page
let Goto = {
    Templates: () => {
        cy.get('a[href$="/templates"]:visible').first().click();
    },
};

let Navigation = {
    Components,
    ...Goto
};

export default Navigation;
