---
name: Notify Dependency Update Template
about: Regular dependency updates
title: Regular Update for Dependencies
labels: Notify, QA, Tech Debt
assignees: ''

---

## User Story - Business Need

We wish to keep dependencies up to date so we do not need such massive overhauls of our system. This will be a recurring ticket that will be done every sprint. We will update all dependencies we are able to. Any conflicts will get a ticket. This is intended to be a day of work at most because this is intended to update with only non-breaking changes.

- [ ] Ticket is understood and QA has been contacted

### User Story
**As** VA Notify
**I want** to keep our service up to date
**So that** we are secure and as free of bugs as possible

### Additional Info and Resources
- Relevant section of [README.md](https://github.com/department-of-veterans-affairs/notification-api#update-requirementstxt)

## Engineering Checklist

- [ ] Update performed
- [ ] Dependabot issues updated
- [ ] Any conflicts removed and tickets created
- [ ] Passes all tests locally
- [ ] Passes userflows and QA Suite testing against Dev
- [ ] Any major changes are investigated (compare existing to new version changes)
  - [ ] Any questionable version changes are removed and a ticket is created
- [ ] Tickets created are added to the Epic for tracking purposes

## Acceptance Criteria
Repo dependencies are updated and we have no broken functionality. Issues opened by Dependabot are resolved. Tickets created for any updates we could, or should, not do.

## QA Considerations
- [ ] Check to see if these updates cancel out any Twistlock issues
- [ ] QA Regression tests pass after deploying this code.
