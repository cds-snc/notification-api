## User Story - Business Need

We wish to keep our lambda dependencies up to date so we do not need such massive overhauls of our system. This will be a recurring ticket. We will update all dependencies we are able to. Any conflicts will get a new ticket. This is intended to be a day of work at most because this is intended to update with only non-breaking changes.

- [ ] Ticket is understood and QA has been contacted

### User Story
**As** VA Notify  
**I want** to keep our lambdas up to date  
**So that** we are secure and as free of bugs as possible

### Additional Info and Resources
In the kafka repo there is a script that can be used to update the lambda layers, find it [here](https://github.com/department-of-veterans-affairs/notification-kafka/blob/main/scripts/create-update-lambda-layers.sh) 

## Engineering Checklist
**Please note, layers are in infra, so you may need PRs in multiple repos to address updates.**

- [ ] Check Dependabot issues for lambda dependency updates - ensure they will be closed with updates
- [ ] Use [this script](https://github.com/department-of-veterans-affairs/notification-kafka/blob/main/scripts/create-update-lambda-layers.sh) in the kafka repo to update lambda layers
	- [ ] copy the updated lambda layers to the infra repo and override the existing layers in `cd/application-infrastructure/lambda_layers/` so they can be deployed
	- [ ] Update the requirements files in the `lambda_layer_requirements` folder in the kafka repo with updated versions
- [ ] Create infra and kafka repo PRs with updated lambda layers
- [ ] Any major version changes are investigated (compare version change logs)
	- [ ] Any questionable version changes are removed and a ticket is created
- [ ] Test in Dev environment (or staging if required for specific lambdas)

## Acceptance Criteria
- [ ] Lambda dependencies are updated and we have no broken functionality. 
- [ ] Issues opened by Dependabot and related to lambdas are resolved. 
- [ ] Tickets created for any updates that interfere with current functionality.
- [ ] In AWS Lambda console, verify that lambdas with updated dependency layers are actually using the newest revisions of the layers.  (This might require a manual change.)
## QA Considerations
- [ ] Check to see if these updates cancel out any Twistlock issues
- [ ] QA Regression tests pass after deploying this code.
- [ ] Any lambdas not tested by the regression are tested with the developer working this ticket
