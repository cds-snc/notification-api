/// <reference types="cypress" />

import config from "../../../config";

const pages = [
    // { en: "/accessibility", fr: "/accessibilite" },
    { en: "/features", fr: "/fonctionnalites" },
    // { en: "/formatting-guide", fr: "/guide-mise-en-forme" },
    // { en: "/guidance", fr: "/guides-reference" },
    { en: "/home", fr: "/accueil" },
    // { en: "/message-delivery-status", fr: "/etat-livraison-messages" },
    // { en: "/other-services", fr: "/autres-services" },
    // { en: "/personalisation-guide", fr: "/guide-personnalisation" },
    // { en: "/privacy", fr: "/confidentialite" },
    // { en: "/privacy-old", fr: "/confidentialite-old" },
    // { en: "/security", fr: "/securite" },
    // { en: "/security-old", fr: "/securite-old" },
    // { en: "/spreadsheets", fr: "/feuille-de-calcul" },
    // { en: "/terms", fr: "/conditions-dutilisation" },
    { en: "/why-gc-notify", fr: "/pourquoi-gc-notification" },
];

const ADMIN_COOKIE = "notify_admin_session";

describe('GCA static pages', () => {
    before(() => {
        Cypress.config('baseUrl', config.Admin.HostName); // use hostname for this environment
    });

    // preserve cookie to keep langauge setting between tests
    beforeEach(() => {
        Cypress.Cookies.preserveOnce(ADMIN_COOKIE);

    });
    afterEach(() => {
        // cy.get('main').htmlvalidate({
        //     rules: {
        //         "no-redundant-role": "off",
        //     },
        // });
    });
    context('English', () => {
        for (const page of pages) {
            it(`can load ${page.en} page`, () => {
                cy.visit(page.en);
                cy.get('main').should('be.visible');

                // check for a11y compliance
                cy.injectAxe();
                cy.checkA11y();
            });
        }
    });

    context('Francais', () => {
        // switch to french before getting french pages
        before(() => {
            cy.visit('/set-lang');
        });

        for (const page of pages) {
            it(`can load ${page.fr} page`, () => {
                cy.visit(page.fr);
                cy.get('main').should('be.visible');

                // check for a11y compliance
                cy.injectAxe();
                cy.checkA11y();
            });
        }
    });
});