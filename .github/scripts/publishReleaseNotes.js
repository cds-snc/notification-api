// publishReleaseNotes.js
const { appendSummary, getReleaseVersionValue } = require('./actionUtils');

// use the gh api getRelease to grab the draft release based on its unique identifier output from the create-release-notes.yml.

async function updateDraftRelease(github, owner, repo, release_id) {
  try {
    const response = await github.rest.repos.updateRelease({
      owner,
      repo,
      release_id,
      draft: false,
    });

    const updateResponse = response.data;
    const releaseUrl = response.data.html_url;

    console.log('Release successfully published at:', releaseUrl);
    console.log('update response is:', updateResponse);

    return { releaseUrl, updateResponse };
  } catch (error) {
    console.error('Error publishing release:', error);
  }
}

async function publishReleaseNotes(params) {
  const { github, context, core } = params;
  const { draftReleaseReference } = process.env;
  const owner = context.repo.owner;
  const repo = context.repo.repo;

  try {
    // publish the draft release
    //
    const { draftReleaseReference } = process.env;

    const { releaseUrl, updateResponse } = await updateDraftRelease(
      github,
      owner,
      repo,
      draftReleaseReference,
    );

    summaryContent = `
### Release has been published!
[Link to notification-api's latest release](${releaseUrl})
	`;
    appendSummary(core, summaryContent);

    console.log(`The draft release reference is: ${draftReleaseReference}`);
  } catch (error) {
    core.setFailed(`Failed to generate summary: ${error.message}`);
    console.error(error);
  }
}

module.exports = publishReleaseNotes;
