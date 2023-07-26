/// <reference types="cypress" />

import config from "../../../../config";
import { LoginPage } from "../../../Notify/Admin/Pages/all";

const pages = [
    { name: "Landing page", route: "/accounts" }, 
    { name: "Your profile", route: "/user-profile" },
    { name: "Dashboard", route: `/services/${config.Services.Cypress}` },
    { name: "Dashboard > Notification reports", route: `/services/${config.Services.Cypress}/notifications/email?email?status=sending,delivered,failed` },
    { name: "Dashboard > Problem emails", route: `/services/${config.Services.Cypress}/problem-emails` },
    { name: "Dashboard > Monthly usage", route: `/services/${config.Services.Cypress}/monthly` },
    { name: "Dashboard > Template usage", route: `/services/${config.Services.Cypress}/template-usage` },
    { name: "Dashboard > Create template", route: `/services/${config.Services.Cypress}/templates/create?source=dashboard` },
    { name: "Dashboard > Choose template", route: `/services/${config.Services.Cypress}/templates?view=sending` },
    { name: "API", route: `/services/${config.Services.Cypress}/api` },
    { name: "API > Keys", route: `/services/${config.Services.Cypress}/api/keys` },
    { name: "API > Keys > Create", route: `/services/${config.Services.Cypress}/api/keys/create` },
    { name: "API > Safelist", route: `/services/${config.Services.Cypress}/api/safelist` },
    { name: "API > Callbacks", route: `/services/${config.Services.Cypress}/api/callbacks/delivery-status-callback` },
    { name: "Team members", route: `/services/${config.Services.Cypress}/users` },
    { name: "Settings", route: `/services/${config.Services.Cypress}/service-settings` },
    { name: "Settings > Change service name", route: `/services/${config.Services.Cypress}/service-settings/name` },
    { name: "Templates", route: `/services/${config.Services.Cypress}/templates` },
    { name: "Template > View template", route: `/services/${config.Services.Cypress}/templates/${config.Templates.SMOKE_TEST_EMAIL}` },
    { name: "Template > Edit template", route: `/services/${config.Services.Cypress}/templates/${config.Templates.SMOKE_TEST_EMAIL}/edit` },
    { name: "Template > Preview template", route: `/services/${config.Services.Cypress}/templates/${config.Templates.SMOKE_TEST_EMAIL}/preview` },
    { name: "GC Notify Activity", route: '/activity' },
    { name: "Contact us", route: '/contact' },
    { name: "Create an account", route: '/register' },
    { name: "Sign in", route: '/sign-in' },
];


describe(`A11Y - App pages [${config.CONFIG_NAME}]`, () => {
    before(() => {
        Cypress.config('baseUrl', config.Hostnames.Admin); // use hostname for this environment
        LoginPage.Login(Cypress.env('NOTIFY_USER'), Cypress.env('NOTIFY_PASSWORD'));
    });
    
    // for (const viewport of config.viewports) {
    //     context(`Viewport: ${viewport}px x 660px`, () => {
    //         context('English', () => {
                for (const page of pages) {
                    context(`${page.name}`, () => {                        
                        it('A11Y checks', () => {
                            cy.visit(page.route);
                            cy.get('main').should('be.visible');
                            cy.log('Checking accessibility compliance...')
                            cy.injectAxe();
                            cy.checkA11y();
                        });
                        it('HTML validation', () => {
                            cy.log('Validating HTML...');
                            cy.get('main').htmlvalidate({
                                rules: {
                                    "no-redundant-role": "off",
                                },
                            });
                        });
                    });
                }
    //         });
    //     })
    // }
});