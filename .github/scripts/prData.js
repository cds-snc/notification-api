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
 * Retrieves the SHA of the main branch's latest commit.
 * @param {Object} github - The GitHub client instance.
 * @param {string} owner - The owner of the GitHub repository.
 * @param {string} repo - The repository name.
 * @returns {Promise<string>} - A promise resolving to the SHA of the latest commit on the main branch.
 */
async function fetchMainBranchSha(github, owner, repo, ref) {
  const { data } = await github.rest.repos.getCommit({
    owner,
    repo,
    ref: ref
  });

  if (data && data.sha) {
    console.log('The SHA of the merge commit is: ' + data.sha);
    return data.sha;
  } else {
    throw new Error('No SHA found in the response');
  }
}

/**
 * Processes labels from pull requests to determine the new version and relevant labels for a release.
 * @param {Array<Object>} labels - An array of label objects from pull requests.
 * @param {string} currentVersion - The current release version.
 * @returns {Object} - An object containing the new version and label.
 */
function processLabelsAndVersion(labels, currentVersion) {
  // Split the current version into major, minor, and patch parts
  let versionParts = currentVersion.split('.').map((x) => parseInt(x, 10));
  
  // Extract the label names from the labels array
  const labelNames = labels.map(labelObj => labelObj.name);
  
  let label; // To store the resulting label for the version bump

  // Determine the type of version bump based on the presence of labels
  if (labelNames.includes('major')) {
    // Major version bump
    versionParts[0] += 1;
    versionParts[1] = 0;
    versionParts[2] = 0;
    label = 'major';
  } else if (labelNames.includes('minor')) {
    // Minor version bump
    versionParts[1] += 1;
    versionParts[2] = 0;
    label = 'minor';
  } else {
    // Patch version bump (default)
    versionParts[2] += 1;
    label = 'patch';
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
    const mainBranchSha = await fetchMainBranchSha(github, owner, repo, sha);

    const labels = pullRequestData.data[0].labels;
    const prNumber = pullRequestData.data[0].number;
    const prUrl = pullRequestData.data[0].html_url;

    const { newVersion, label } = processLabelsAndVersion(
      labels,
      currentVersion,
    );

    return {
      mainBranchSha,
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
