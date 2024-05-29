// actionUtils.js

// This module provides various utilities that are used by multiple other scripts

const fs = require('fs'); // NodeJs module provides an API for interacting with the file system

/**
 * Appends a provided summary content to the GitHub step summary file.
 *
 * @param {object} core A reference to the @actions/core package
 * @param {string} summaryContent The content to append to the GitHub step summary.
 * @returns {Promise<void>} A Promise that resolves with no value (undefined) if the append operation succeeds,
 *                          or rejects if an error occurs during the append operation.
 */
async function appendSummary(core, summaryContent) {
  try {
    fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, summaryContent);
    console.log('Summary appended successfully.');
  } catch (error) {
    core.setFailed('Failed to append summary due to: ' + error.message);
    console.error(error);
  }
}

/**
 * Retrieves the current release version from a repository's actions secrets.
 * @param {Object} github - The GitHub client instance.
 * @param {string} owner - The owner of the GitHub repository.
 * @param {string} repo - The repository name.
 * @returns {Promise<string>} - A promise resolving to the current release version.
 */
async function getReleaseVersionValue(github, owner, repo) {
  const { data } = await github.rest.actions.getRepoVariable({
    owner,
    repo,
    name: 'RELEASE_VERSION',
  });
  return data.value;
}

module.exports = {
  appendSummary,
  getReleaseVersionValue,
};
