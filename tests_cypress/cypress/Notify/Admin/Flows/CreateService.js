export default (name) => {
    // Create and configure new service
    cy.visit("/accounts");

    // Click add service
    cy.get("a[href='/add-service'").click();
    cy.location("href").should("contain", "/add-service");
    // Click next
    cy.get('button[type="submit"]').click();
    // Enter service name
    cy.get("#name").click();
    cy.get("#name").type(name);
    // enter sernding name
    cy.get("#email_from").click();
    cy.get("#email_from").type(`send_${Math.random().toString(36).slice(2)}_name`);
    // Submit
    cy.get('button[type="submit"]').click();

    // Return to dashboard
    cy.contains('h1', 'Dashboard').should('be.visible');
}