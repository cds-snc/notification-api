/// <reference types="cypress" />

import config from "../../../../config";

const pages = [
    { en: "/accessibility", fr: "/accessibilite" },
    { en: "/keep-accurate-contact-information", fr: "/maintenez-a-jour-les-coordonnees"},
    { en: "/delivery-and-failure", fr: "/livraison-reussie-et-echec"},
    { en: "/features", fr: "/fonctionnalites" },
    { en: "/formatting-guide", fr: "/guide-mise-en-forme" },
    { en: "/guidance", fr: "/guides-reference" },
    { en: "/home", fr: "/accueil" },
    { en: "/message-delivery-status", fr: "/etat-livraison-messages" },
    { en: "/other-services", fr: "/autres-services" },
    { en: "/personalisation-guide", fr: "/guide-personnalisation" },
    { en: "/privacy", fr: "/confidentialite" },
    { en: "/privacy-old", fr: "/confidentialite-old" },
    { en: "/security", fr: "/securite" },
    { en: "/security-old", fr: "/securite-old" },
    { en: "/spreadsheets", fr: "/feuille-de-calcul" },
    { en: "/terms", fr: "/conditions-dutilisation" },
    { en: "/why-gc-notify", fr: "/pourquoi-gc-notification" },
];

const ADMIN_COOKIE = "notify_admin_session";

describe('GCA static pages', () => {
    before(() => {
        Cypress.config('baseUrl', config.Hostnames.Admin); // use hostname for this environment
    });
    afterEach(() => {
        // cy.get('main').htmlvalidate({
        //     rules: {
        //         "no-redundant-role": "off",
        //     },
        // });
    });
    console.log(config.viewports)
    for (const viewport of config.viewports) {
        context(`Viewport: ${viewport}px x 660px`, () => {
            context('English', () => {
                for (const page of pages) {
                    it(`${page.en} passes a11y checks`, () => {
                        cy.viewport(viewport, 660);
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
                        cy.viewport(viewport, 660);
        
                        cy.visit(page.fr);
                        cy.get('main').should('be.visible');
                        // check for a11y compliance
                        cy.injectAxe();
                        cy.checkA11y();
                    
                    });
                }
            });
        })
    }
    
});