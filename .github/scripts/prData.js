// prData.js
const { getReleaseVersionValue } = require('./actionUtils');

/**
 * Fetches all pull requests associated with a specific commit from a GitHub repository.
 * @param {Object} github - The GitHub client instance.
 * @param {string} owner - The owner of the GitHub repository.
 * @param {string} repo - The repository name.
 * @param {string} sha - The commit SHA.
 * @returns {Promise<Object>} - A promise resolving to the list of pull requests.
 */
async function fetchPullRequests(github, owner, repo, sha) {
  return await github.rest.repos.listPullRequestsAssociatedWithCommit({
    owner,
    repo,
    commit_sha: sha,
  });
}

/**
 * Retrieves the SHA of the release branch's latest commit.
 * @param {Object} github - The GitHub client instance.
 * @param {string} owner - The owner of the GitHub repository.
 * @param {string} repo - The repository name.
 * @returns {Promise<string>} - A promise resolving to the SHA of the latest commit on the release branch.
 */
async function fetchReleaseBranchSha(github, owner, repo) {
  const { data } = await github.rest.repos.getCommit({
    owner,
    repo,
    ref: 'heads/release',
  });

  if (data && data.sha) {
    console.log('The release branch head SHA is: ' + data.sha);
    return data.sha;
  } else {
    throw new Error('No SHA found in the response');
  }
}

/**
 * Processes labels from pull requests to determine the new version and relevant labels for a release.
 * EXPECTS ONLY ONE LABEL, as is currently our process for merging PRs
 * @param {Array<Object>} labels - An array of label objects from pull requests.
 * @param {string} currentVersion - The current release version.
 * @returns {Object} - An object containing the new version and label.
 */
function processLabelsAndVersion(labels, currentVersion) {
  // Split the current version into major, minor, and patch parts
  let versionParts = currentVersion.split('.').map((x) => parseInt(x, 10));
  let label = labels[0].name;

  // Determine the type of version bump based on the label
  if (label === 'breaking-change') {
    // Major version bump
    versionParts[0] += 1;
    versionParts[1] = 0;
    versionParts[2] = 0;
  } else if (['hotfix', 'security', 'bug', 'internal'].includes(label)) {
    // Patch version bump
    versionParts[2] += 1;
  } else {
    // Minor version bump
    versionParts[1] += 1;
    versionParts[2] = 0;
  }

  // newVersion is in the format X.X.X
  return {
    newVersion: versionParts.join('.'),
    label,
  };
}

/**
 * Main function to handle pull request data for a GitHub repository.
 * @param {Object} params - Parameters including GitHub client and context.
 * @returns {Promise<Object>} - An object containing pull request processing results or null in case of error.
 */
async function prData(params) {
  const { github, context, core } = params;
  const owner = context.repo.owner;
  const repo = context.repo.repo;
  const sha = context.payload.after;

  try {
    const pullRequestData = await fetchPullRequests(github, owner, repo, sha);
    const currentVersion = await getReleaseVersionValue(github, owner, repo);
    const releaseBranchSha = await fetchReleaseBranchSha(github, owner, repo);

    const labels = pullRequestData.data[0].labels;
    const prNumber = pullRequestData.data[0].number;
    const prUrl = pullRequestData.data[0].html_url;

    const { newVersion, label } = processLabelsAndVersion(
      labels,
      currentVersion,
    );

    return {
      releaseBranchSha,
      currentVersion,
      newVersion,
      label,
      prNumber,
      prUrl,
    };
  } catch (error) {
    core.setFailed(`Error processing PR data: ${error.message}`);
    console.error('Error processing PR data:', error);
    return null; // Ensure to handle null in postQA.js if needed
  }
}

module.exports = {
  prData,
};
