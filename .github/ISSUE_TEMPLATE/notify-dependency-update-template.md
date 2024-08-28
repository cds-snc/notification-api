---
name: Notify Dependency Update Template
about: Regular dependency updates
title: Regular Update for Dependencies
labels: Notify, QA, Tech Debt
assignees: ''
---

## User Story - Business Need

We wish to keep dependencies up to date so that we do not need such massive overhauls of our system. This is a recurring task to update all dependencies we are able to update. Any conflicts shall get a dedicated ticket. This task should be a day of work at most because it only updates non-breaking changes.

- [ ] Ticket is understood and QA has been contacted

### User Story

**As** VA Notify,
**I want** to keep our service up to date
**So that** we are secure and as free of bugs as possible.

### Additional Info and Resources

- Relevant section of [README.md](https://github.com/department-of-veterans-affairs/notification-api#update-dependencies)
- Troubleshooting tips:
  - When looking at changes in `poetry.lock`, revert major changes, then minor, then patch/security: **never** edit this file manually!


## Engineering Checklist

- [ ] Review "Tech Debt" tickets in backlog to identify packages already known to have breaking changes (**don't try to upgrade these**) 
  - pro-tip: these should be pinned down to a specific version in the pyproject.toml file
- [ ] Review [open Dependabot PRs](https://github.com/department-of-veterans-affairs/notification-api/pulls/app%2Fdependabot) to determine where the changes will take place (open them and look at the files touched). 
  -  Do not modify these PRs
- [ ] Update performed per the [README.md](https://github.com/department-of-veterans-affairs/notification-api#update-dependencies)
- [ ] Passes all tests locally
- [ ] Passes QA Suite regression testing against Dev
- [ ] If there are any failures, compare the [poetry.lock in main](https://github.com/department-of-veterans-affairs/notification-api/blob/main/poetry.lock) against your local `poetry.lock`. 
  - [ ] Identify the discrepancies and lock those versions in `pyproject.toml`, create a ticket, and label it "tech debt"
  - [ ] Any non-top level dependencies that have to be locked should have a comment added to `pyproject.toml` and have a checkbox to remove that dependency from `pyproject.toml` in the acceptance criteria
  - [ ] Created ticket has the package name in the title

## Acceptance Criteria

Repo dependencies are updated and we have no broken functionality. Issues opened by Dependabot are resolved. Tickets with the "tech debt" label created for any updates we could, or should, not do.

## QA Considerations

- [ ] Affected Dependabot PRs are closed after merge (may need to rebase them using dependabot command)
- [ ] Check to see if these updates cancel out any Twistlock issues
- [ ] QA Regression tests pass after deploying this code.
