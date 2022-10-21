const { defineConfig } = require("cypress");
const EmailAccount = require('./cypress/plugins/email-account')

module.exports = defineConfig({
  e2e: {
    setupNodeEvents: async (on, config) => {
      const emailAccount = await EmailAccount()

      on('task', {
        getLastEmail() {
          return emailAccount.getLastEmail()
        },
        deleteAllEmails() {
          return emailAccount.deleteAllEmails()
        }
      });

      on('before:browser:launch', (browser = {}, launchOptions) => {
        if (browser.family === 'chromium' && browser.name !== 'electron') {
          launchOptions.extensions = [];
        }
        return launchOptions;
      });
    },
    specPattern: '**/e2e/*.cy.js',
    watchForFileChanges: false
  },
});
