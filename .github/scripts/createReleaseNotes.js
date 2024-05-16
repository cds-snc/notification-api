// createReleaseNotes.js
const { appendSummary, getReleaseVersionValue } = require("./actionUtils");

/**
 * Formats the current date in a specific string format for use in release titles.
 *
 * @returns {string} The formatted date string in the format: DD MMM YYYY (e.g., "15 MAY 2024").
 */
function formatDate() {
  const date = new Date();
  const options = { day: "2-digit", month: "short", year: "numeric" };
  return date.toLocaleDateString("en-US", options).toUpperCase();
}

/**
 * Creates a draft release on GitHub with a specified tag and release notes.
 *
 * @param {Object} github The authenticated GitHub API client instance.
 * @param {string} owner The username or organization name on GitHub that owns the repository.
 * @param {string} repo The repository name.
 * @param {string} tag_name The tag associated with the release.
 * @param {string} body The content of the release notes.
 * @returns {Promise<string>} A Promise that resolves with the URL of the newly created draft release.
 */
async function createDraftRelease(github, owner, repo, tag_name, body) {
  try {
    const response = await github.rest.repos.createRelease({
      owner,
      repo,
      tag_name,
      name: `${tag_name} - ${formatDate()}`,
      body,
      draft: true,
      prerelease: false,
    });

    const releaseUrl = response.data.html_url;
    console.log("Release URL:", releaseUrl);
    return releaseUrl;
  } catch (error) {
    console.error("Error creating release:", error);
  }
}

/**
 * Generates release notes by comparing the current tag with a previous tag using GitHub's API.
 *
 * @param {Object} github The authenticated GitHub API client instance.
 * @param {string} owner The username or organization name on GitHub that owns the repository.
 * @param {string} repo The repository name.
 * @param {string} tag_name The current tag for which to generate release notes.
 * @param {string} previous_tag_name The previous tag to compare against for generating release notes.
 * @returns {Promise<Object>} A Promise that resolves with an object containing the response and the generated release notes.
 */
async function generateReleaseNotes(
  github,
  owner,
  repo,
  tag_name,
  previous_tag_name,
) {
  try {
    const response = await github.rest.repos.generateReleaseNotes({
      owner,
      repo,
      tag_name,
      // target_commitish: 'main',
      previous_tag_name,
      configuration_file_path: ".github/release.yaml",
    });
    const releaseNotes = response.data.body;
    console.log("Release notes generated successfully:", response);
    return { response, releaseNotes };
  } catch (error) {
    console.error("Error generating release notes:", error);
  }
}

/**
 * Main function to create release notes, create a draft release, and append a summary.
 *
 * @param {Object} params An object containing the GitHub API client, the GitHub context, and the GitHub core library.
 * @returns {Promise<void>} A Promise that resolves with no value indicating the successful creation and summary of release notes.
 */
async function createReleaseNotes(params) {
  const { github, context, core } = params;
  const { previousVersion } = process.env;
  const owner = context.repo.owner;
  const repo = context.repo.repo;

  try {
    // get currentVersion for release and release notes
    const currentVersion = await getReleaseVersionValue(github, owner, repo);

    // generate release notes based on the previousVersion
    const { releaseNotes, response } = await generateReleaseNotes(
      github,
      owner,
      repo,
      currentVersion,
      previousVersion,
    );
    //
    // create release, attach generated notes, and return the url for the step summary
    const releaseUrl = await createDraftRelease(
      github,
      owner,
      repo,
      currentVersion,
      releaseNotes,
    );

    // Make a github summary that provides a link to the draft release and notifies of successful creation
    summaryContent = `
### Release Notes Created!
[Link to the draft release notes](${releaseUrl})
Draft notes created based on the update to ${currentVersion} 
and comparing the tag from the previous version: ${previousVersion}
    `;
    appendSummary(core, summaryContent);

    // Output the previous version to the console
    console.log(`The previous release version was: ${previousVersion}`);
  } catch (error) {
    core.setFailed(`Failed to generate summary: ${error.message}`);
    console.error(error);
  }
}

module.exports = createReleaseNotes;
