// prLabelSemver.js
const { prData } = require('./prData');
const { appendSummary } = require('./actionUtils');

/**
 * Helper function to determine the semver update type based on a single label.
 *
 * @param {string} label - The label of the pull request.
 * @returns {string} The semver value corresponding to the label.
 */
function determineSemverValue(label) {
  console.log('Received label:', label);

  try {
    if (label.includes('breaking change')) {
      return 'MAJOR';
    } else if (
      label.includes('hotfix') ||
      label.includes('security') ||
      label.includes('internal') ||
      label.includes('bug')
    ) {
      return 'PATCH';
    } else {
      return 'MINOR';
    }
  } catch (error) {
    console.error('Error determining semver value:', error);
    return 'UNKNOWN';
  }
}

/**
 * Automatically labels pull requests based on semantic versioning (semver) guidelines
 * and appends a summary to the GitHub action step.
 *
 * @param {object} params - The parameters containing github, context, and core objects.
 * @returns {Promise<void>} A Promise that resolves when the summary has been successfully appended,
 *                          or rejects if an error occurs during the operation.
 */
async function prLabelSemver(params) {
  const { github, context, core } = params;

  try {
    // Retrieve necessary data from prData.js
    const { label, prNumber, prUrl } = await prData({ github, context, core });

    // Determine the semver update type based on the labels
    const semverValue = determineSemverValue(label);

    // Construct the summary content
    const summaryContent = `
### PR Label Semver Summary
- PR Number: [#${prNumber}](${prUrl})
- Label: ${label}
- Semver Bump: ${semverValue}
`;
    // Append the summary to the GitHub step summary file or log it
    appendSummary(core, summaryContent);
  } catch (error) {
    core.setFailed(`Failed to generate summary: ${error.message}`);
    console.error(error);
  }
}

module.exports = prLabelSemver;
