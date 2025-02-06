// createReleaseNotes.js
const { appendSummary, getReleaseVersionValue } = require('./actionUtils');

/**
 * Formats the current date in a specific string format for use in release titles.
 * @returns {string} The formatted date string in the format: DD MMM YYYY (e.g., "15 MAY 2024").
 */
function formatDate() {
  const date = new Date();
  const options = { day: '2-digit', month: 'short', year: 'numeric' };
  return date.toLocaleDateString('en-US', options).toUpperCase();
}

/**
 * Creates a published release on GitHub with generated release notes.
 *
 * @param {Object} params An object containing the GitHub API client, context, and core library.
 * @returns {Promise<void>} A promise that resolves when the release has been created.
 */
async function createReleaseNotes(params) {
  const { github, context, core } = params;
  const owner = context.repo.owner;
  const repo = context.repo.repo;
  const { previousVersion } = process.env;

  try {
    // Retrieve the current version (e.g., from a tag or other mechanism)
    const currentVersion = await getReleaseVersionValue(github, owner, repo);

    // Generate release notes comparing the current version to the previous version
    const releaseNotesResponse = await github.rest.repos.generateReleaseNotes({
      owner,
      repo,
      tag_name: currentVersion,
      previous_tag_name: previousVersion,
      configuration_file_path: '.github/release.yaml',
    });
    const releaseNotes = releaseNotesResponse.data.body;

    // Create the release (published immediately, not a draft)
    const createReleaseResponse = await github.rest.repos.createRelease({
      owner,
      repo,
      tag_name: currentVersion,
      name: `${currentVersion} - ${formatDate()}`,
      body: releaseNotes,
      draft: false,
      prerelease: false,
    });
    const releaseUrl = createReleaseResponse.data.html_url;

    // Append a summary message for visibility in GitHub Actions
    const summaryContent = `
### Release Created Successfully!
- **Version:** ${currentVersion}
- **Release URL:** [View Release](${releaseUrl})
- **Compared to Previous Version:** ${previousVersion}
    `;
    appendSummary(core, summaryContent);

    // Set output for downstream steps if needed
    core.setOutput('releaseUrl', releaseUrl);

    console.log('Release created successfully at:', releaseUrl);
  } catch (error) {
    core.setFailed(`Failed to create release: ${error.message}`);
    console.error('Error creating release:', error);
  }
}

module.exports = createReleaseNotes;
