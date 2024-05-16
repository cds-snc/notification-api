// prLabelSemver.js
const { prData } = require("./prData");
const { appendSummary } = require("./actionUtils");

/**
 * Automatically labels pull requests based on semantic versioning (semver) guidelines
 * and appends a summary to the GitHub action step.
 *
 * @param {object} github - The github object providing context and operations for the pull request.
 * @param {object} context - The context object containing metadata and states for the action run.
 * @param {object} core - The core library with utilities for logging and error handling.
 * @returns {Promise<void>} A Promise that resolves when the summary has been successfully appended,
 *                          or rejects if an error occurs during the operation.
 */
async function prLabelSemver(params) {
  const { github, context, core } = params;

  try {
    // Retrieve necessary data from prData.js
    const { label, prNumber, prUrl } = await prData({ github, context, core });

    // Determine the semver update type based on the label
    const semverValue = label.includes("breaking change")
      ? "MAJOR"
      : label.includes("hotfix") ||
          label.includes("security") ||
          label.includes("bug")
        ? "PATCH"
        : "MINOR";

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
