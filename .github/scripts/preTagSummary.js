// preTagSummary.js
// This module defines a function to generate a pre-tag release summary for GitHub pull requests.
const { prData } = require('./prData');
const { appendSummary } = require('./actionUtils');

/**
 * Asynchronously generates and appends a pre-tag release summary to the GitHub step summary file.
 * This function retrieves the current and proposed new release versions from a pull request data,
 * constructs a summary of the release, and appends it to the GitHub step summary for visibility
 * in the GitHub Actions workflow.
 *
 * @param {object} github - The GitHub context object, providing context like repo and owner.
 * @param {object} context - The GitHub context object with additional pull request information.
 * @param {object} core - The GitHub core library, used for setting action failure messages.
 * @returns {Promise<void>} A Promise that resolves when the summary has been successfully appended,
 *                          or rejects if an error occurs during the operation.
 */
async function preTagSummary(params) {
  const { github, context, core } = params;

  try {
    // Retrieve the current release version and proposed new version from prData
    const { currentVersion, newVersion } = await prData({
      github,
      context,
      core,
    });

    // Construct the summary content
    const summaryContent = `
### Pre-Tag Release Summary
- Current Release Version: ${currentVersion}
- New Version upon Merge: ${newVersion}
`;

    // Append the summary to the GitHub step summary file or log it
    appendSummary(core, summaryContent);
  } catch (error) {
    core.setFailed(`Failed to generate summary: ${error.message}`);
    console.error(error);
  }
}

module.exports = preTagSummary;
