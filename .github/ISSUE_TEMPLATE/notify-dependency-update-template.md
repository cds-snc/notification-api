---
name: Notify Dependency Update Template
about: Regular dependency updates
title: Regular Update for Dependencies
labels: Notify, QA, Tech Debt
assignees: ''
---

## User Story - Business Need

We wish to keep dependencies up to date so we do not need such massive overhauls of our system. This is a recurring task to update all dependencies we are able to update. Any conflicts shall get a dedicated ticket. This task should be a day of work at most because it only updates non-breaking changes.

- [ ] Ticket is understood and QA has been contacted

### User Story

**As** VA Notify,
**I want** to keep our service up to date
**So that** we are secure and as free of bugs as possible.

### Additional Info and Resources

- Relevant section of [README.md](https://github.com/department-of-veterans-affairs/notification-api#update-requirementstxt)

## Engineering Checklist

- [ ] Open "Tech Debt" issues reviewed to identify packages already known to have breaking changes (don't try to upgrade these)
- [ ] Review [open Dependabot PRs](https://github.com/department-of-veterans-affairs/notification-api/pulls/app%2Fdependabot) to determine where the changes will take place. You may need to rebase older PRs.  The PRs explain how to do this.
- [ ] Update performed
- [ ] Dependabot PRs updated.  (They should automatically close if a given dependency was upgrade at least to the version given by the PR.)
- [ ] Any conflicts removed and tickets created with the "tech debt" label
- [ ] Passes all tests locally
- [ ] Passes QA Suite regression testing against Dev
- [ ] Any major version changes are investigated (compare existing to new version change logs)
  - [ ] Any questionable version changes are removed and a ticket with the "tech debt" label is created

## Acceptance Criteria

Repo dependencies are updated and we have no broken functionality. Issues opened by Dependabot are resolved. Tickets with the "tech debt" label created for any updates we could, or should, not do.

## QA Considerations

- [ ] Check to see if these updates cancel out any Twistlock issues
- [ ] QA Regression tests pass after deploying this code.
