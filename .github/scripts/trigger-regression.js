// This script is capable of triggering a specified workflow, waiting for its completion, 
// and then logging the conclusion of a job in a nice summary

// Access the environment input from environment variables
const { ENVIRONMENT } = process.env;

const inputs = {
  environment: ENVIRONMENT,
};

const triggerAndWait = async ({ github, core }) => {
  const owner = 'department-of-veterans-affairs'; // user of private repo 
  const repo = 'notification-api-qa'; // private repo to contact
  const workflow_id = 'regression.yml'; // Replace with your workflow file name or ID
  const ref = 'master'; // Usually main or master.  THIS IS THE REF of the REGRESSION repo!
  const jobName = `Test in ${ENVIRONMENT}`; // Replace with the name of the job you want

  // Create a timestamp for workflow run tracking
  const triggerTimestamp = new Date().toISOString();
  console.log(`Triggering workflow: ${workflow_id} on ${owner}/${repo}`);
  await github.rest.actions.createWorkflowDispatch({
    owner,
    repo,
    workflow_id,
    ref,
    inputs,
  });

  // Wait a moment for the workflow run to be initialized
  await new Promise(r => setTimeout(r, 5000));

  // Poll for the workflow run using the timestamp
  let run_id;
  while (!run_id) {
    const runs = await github.rest.actions.listWorkflowRuns({
      owner,
      repo,
      workflow_id,
      created: `>=${triggerTimestamp}`
    });

    if (runs.data.workflow_runs.length > 0) {
      run_id = runs.data.workflow_runs[0].id;
      break;
    }

    await new Promise(r => setTimeout(r, 1000));
  }

  console.log(`Triggered workflow run ID: ${run_id}`);

  // Wait for the workflow to complete
  let status;
  let conclusion;
  let workflow_url = `https://github.com/${owner}/${repo}/actions/runs/${run_id}`;
  do {
    await new Promise(r => setTimeout(r, 30000)); // Poll every 30 seconds
    const result = await github.rest.actions.getWorkflowRun({
      owner,
      repo,
      run_id,
    });
    status = result.data.status;
    conclusion = result.data.conclusion;
    console.log(`Current status: ${status}`);
  } while (status !== 'completed');

  // Log the conclusion and the workflow URL
  console.log(`Workflow conclusion: ${conclusion}`);
  console.log(`Workflow run URL: ${workflow_url}`);

  // Fetch the job within the workflow run
  const jobs = await github.rest.actions.listJobsForWorkflowRun({
    owner,
    repo,
    run_id,
  });

  const job = jobs.data.jobs.find(j => j.name === jobName);
  if (!job) {
    console.log(`Job '${jobName}' not found in workflow run.`);
    return;
  }

  let job_id = job.id;

  // Fetch and handle the job logs
  github.rest.actions.downloadJobLogsForWorkflowRun({
    owner,
    repo,
    job_id,
  }).then(response => {
    console.log(`Job logs: ${response.data}`);
  }).catch(error => {
    console.log('Error fetching job logs:', error);
  });

   // Set the output for the job summary
  const resultText = conclusion === 'success' ? 'passed' : 'failed';
  core.setOutput('regression_result', `QA Regression result is ${resultText}; link to this run is ${workflow_url}`);

  // Append to GITHUB_STEP_SUMMARY
  const summaryContent = `### Workflow Result\nResult: ${resultText}\n[Link to Workflow Run](${workflow_url})`;
  require('fs').appendFileSync(process.env.GITHUB_STEP_SUMMARY, summaryContent);

  // Check if the workflow failed and set an appropriate error message
  if (conclusion !== 'success') {
    const errorMessage = `Workflow failed with conclusion: ${conclusion}. See details: ${workflow_url}`;
    console.error(errorMessage);
    core.setFailed(errorMessage);
  }
};

module.exports = triggerAndWait;




