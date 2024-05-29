// createAndPostTag.js
const { prData } = require('./prData');
const { appendSummary, getReleaseVersionValue } = require('./actionUtils');

/**
 * Creates a new git tag in the repository.
 *
 * @param {object} github The Octokit instance to interact with GitHub API.
 * @param {string} owner The repository owner's name.
 * @param {string} repo The repository name.
 * @param {string} newVersion The new version for the tag.
 * @param {string} sha The SHA of the commit to tag.
 * @returns {Promise<void>} A Promise that resolves when the tag is successfully created and pushed,
 *                          or rejects if an error occurs.
 */
async function createTag(github, owner, repo, newVersion, sha) {
  const tagName = `${newVersion}`;
  const tagMessage = `Release for version ${newVersion}`;

  // Create the tag object (equivalent to creating a local tag)
  const { data: tagData } = await github.rest.git.createTag({
    owner,
    repo,
    tag: tagName,
    message: tagMessage,
    object: sha,
    type: 'commit',
  });

  // Create the reference in the repository (this is equivalent to pushing the tag to the repo)
  await github.rest.git.createRef({
    owner,
    repo,
    ref: `refs/tags/${tagName}`,
    sha: tagData.sha,
  });

  console.log(`Tag ${tagName} created and pushed successfully.`);
}

/**
 * Orchestrates the creation and posting of a new tag to a GitHub repository based on pull request data.
 * This function is used within a GitHub Actions workflow to automate release tagging.
 *
 * @param {object} params - The parameters object containing all necessary data.
 * @param {object} params.github - The Octokit instance used to interact with GitHub.
 * @param {object} params.context - The context of the GitHub action, containing repository and action runner metadata.
 * @param {object} params.core - The core toolkit for GitHub actions to handle logging and errors.
 * @returns {Promise<void>} A Promise that resolves when the summary has been successfully appended,
 *                          or rejects if an error occurs during the operation.
 */
async function createAndPostTag(params) {
  const { github, context, core } = params;
  const owner = context.repo.owner;
  const repo = context.repo.repo;

  try {
    // Retrieve the current release version, this will be used as the previousVersion
    const previousVersion = await getReleaseVersionValue(github, owner, repo);

    // Retrieve PR data to decide the new version tag
    const { releaseBranchSha, newVersion } = await prData({
      github,
      context,
      core,
    });

    // Create and push the tag using the SHA from releaseBranchSha
    await createTag(github, owner, repo, newVersion, releaseBranchSha);

    // Update the RELEASE_VERSION repo variable
    await github.rest.actions.updateRepoVariable({
      owner,
      repo,
      name: 'RELEASE_VERSION',
      value: newVersion,
    });

    // Output previous version to the GitHub actions workflow context
    // This will be used by the workflow that sets up the release notes
    core.setOutput('previousVersion', previousVersion);

    // this output will be the tag used for the staging deploy
    core.setOutput('newVersion', newVersion);

    // Construct the summary content
    const summaryContent = `
### Successful Tag Creation!
- After merge to the release branch, a tag was created.
- Previous version was ${previousVersion}
- New version is ${newVersion}
- Tag created for version ${newVersion} using the new release branch SHA: ${releaseBranchSha}
`;

    // Append the summary to the GitHub step summary file or log it
    appendSummary(core, summaryContent);
  } catch (error) {
    core.setFailed(`Failed to generate summary: ${error.message}`);
    console.error(error);
  }
}

module.exports = createAndPostTag;
