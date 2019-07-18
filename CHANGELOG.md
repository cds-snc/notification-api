## Changelog

The purpose of this file is to track the major changes we have made to the application from the original GDS version and to provide a rational for those changes. Changes are listed in reverse chronological order from most recent to last. Changes are broken down by component (API, ADMIN, UTILS). This list is not comprehensive but should just give an idea of steps necessary to stand up one's own version.

### Changes to API
<https://github.com/cds-snc/notification-api>

- __Change__: Mark all text messages as sent
- __Rational__: Amazon SNS does not provide a simple mechanism for checking if a specific message has been delivered. Until we figure out a solution, all messages are flagged as sent.
- __Commits__: https://github.com/cds-snc/notification-api/commit/b78d2437cb74871f211f21a3071c8a1c2cd98d80
---
- __Change__: Exporting stats to StatsD
- __Rational__: GDS uses a centralized StatsD aggregator. CDS chose to send our StatsD data to Google Stackdriver using the cluster infrastructure.
- __Commits__: https://github.com/cds-snc/notification-api/commit/c142146fbb7b0ac30cb1a96218e7dbcf070078b3
---
- __Change__: Added a status callback for emails sent through SES.
- __Rational__: There was no way for us to get information if an email was delivered or not because SES does not send that information back automagically. Digging around the code base we found that there used to be an API callback from SES through SNS. This was removed and is now running in a lambda according to a GDS commit message with undisclosed source code. We added an API callback back in.
- __Commits__: https://github.com/cds-snc/notification-api/commit/3650bd86caa50fcfb482f9fc52bbd144b8715709
---
- __Change__: Changed the default templates in the database using migrations
- __Rational__: GDS hardcodes GOV.UK in their templates using database migrations. We had to add additional migrations to make our own changes to the template. We also made a migration use SNS as our preferred provider.
- __Commits__: https://github.com/cds-snc/notification-api/commit/447250f12f838b1f2e72c38b34299c281a19976f, https://github.com/cds-snc/notification-api/commit/f4b0f1a09486a47fc78e9d31d9952afc53c070c7, https://github.com/cds-snc/notification-api/commit/c622b5e4c8cce3b3e7aa0fe27b3ea55ca9adbf2f, https://github.com/cds-snc/notification-api/commit/c32a472d60e3f9ed1a328f4624685390b977893d
---
- __Change__: Change the CI/CD process for testing and building.
- __Rational__: CDS uses Google cloud build and Kubernetes engine. Added new docker files that use Alpine as their base vs. the debian images.
- __Commits__: https://github.com/cds-snc/notification-api/commit/5c7ffa4f215fd198cf7825cc733bf7dadb3bef7d
---
- __Change__: Repointed the requirements to use CDS utils vs. GDS utils
- __Rational__: We need to make changes to the utils repository and therefore forked it and repointed the API requirements to that.
- __Commits__: https://github.com/cds-snc/notification-api/commit/dfe9feb71015aff911f913bf717aad442576a2e4
---
- __Change__: Added Amazon SNS as a provider for sending text messages
- __Rational__: GDS currently only support Firetext and MMG to send text messages. CDS has no contract with those vendors but does have access to Amazon SNS as a text message vendor.
- __Commits__: https://github.com/cds-snc/notification-api/commit/c3305d55f7f8007841c045b77feb1f79e703932b, https://github.com/cds-snc/notification-api/commit/875f5d66fee2ce94af0a2a0bf167cfa9bc059c94, https://github.com/cds-snc/notification-api/commit/19e762e34320806c0a128747142e6d2196153c67
---
- __Change__: Refactored how environment variables get loaded and defaults are assigned.
- __Rational__: Environmental variables should be injected by the host (Docker, K8s pod, etc) into an application vs. hardcoded in a file. Sane defaults should exist if they are missing.
- __Commits__: https://github.com/cds-snc/notification-api/commit/0b6954c253151d3dbac1f62152c4de56e843d67c
---
### Changes to ADMIN
<https://github.com/cds-snc/notification-admin>

- __Change__: Mark all text messages as sent
- __Rational__: Amazon SNS does not provide a simple mechanism for checking if a specific message has been delivered. Until we figure out a solution, all messages are flagged as sent.
- __Commits__: https://github.com/cds-snc/notification-admin/commit/47f79dc3885836a0ef8516b0201455c45ee3cdd5
---
- __Change__: Added alpha banner
- __Rational__: Users need to know this product it in Alpha.
- __Commits__: https://github.com/cds-snc/notification-admin/commit/41c54dbc0fd81cc770bbed108d02d272057f2122
---
- __Change__: Removed https://github.com/alphagov/govuk_frontend_toolkit JavaScript and CSS/SASS dependancy.
- __Rational__: It did not make sense to maintain another fork if we could pull these in.
- __Commits__: https://github.com/cds-snc/notification-admin/commit/aa70c20d5e35f6c0051c11e0757b4794161ff86c
---
- __Change__: Update templates to remove GOV.UK branding and added Canada branding. Also removed references to GOV.UK that were hard coded.
- __Rational__: This product should not confuse users to think they are using a GOV.UK platform. 
- __Commits__:https://github.com/cds-snc/notification-admin/commit/d4bd8ba25208a526ea64df8cb24bbc324dc8deff, https://github.com/cds-snc/notification-admin/commit/f2623ec79039833d48a0238efe87fc8886be51d0, https://github.com/cds-snc/notification-admin/commit/c5af3230ea727c66b440bb6493309191f0d82e34, https://github.com/cds-snc/notification-admin/commit/aa70c20d5e35f6c0051c11e0757b4794161ff86c,
https://github.com/cds-snc/notification-admin/commit/9991e2762857d695654717c4125cadb7baab8049
---
- __Change__: Added a language switching toggle and start extracting strings from templates
- __Rational__: Canada is an bilingual country and needs to support both a french and an english version of the app.
- __Commits__: https://github.com/cds-snc/notification-admin/commit/e93ca70791c35717f833f7384eed09c58a731b98, https://github.com/cds-snc/notification-admin/commit/277768935d07030ea98b42824ac932d9026fc7e7, https://github.com/cds-snc/notification-admin/commit/89f06d8c9d0200d186bb326ae2643aba247ec37e, https://github.com/cds-snc/notification-admin/commit/5888bdac2493dd70bb0cbcd8dbc668c2918ef67c
---
- __Change__: Refactored how environment variables get loaded and defaults are assigned.
- __Rational__: Environmental variables should be injected by the host (Docker, K8s pod, etc) into an application vs. hardcoded in a file. Sane defaults should exist if they are missing.
- __Commits__: https://github.com/cds-snc/notification-admin/commit/4f1c55b28d8788a8c26a76ac6525c5d0e8fec121
---
### Changes to UTILS
<https://github.com/cds-snc/notification-utils>

- __Change__: Make locality for telephone number configurable. 
- __Rational__: Phone numbers were either identified as local or international and hardcoded to follow rules set out by UK dialing restrictions.
- __Commits__: https://github.com/cds-snc/notification-utils/commit/cd51e729d63acdab71174fe3666593db2fdf5248
---
- __Change__: Changed timezone from London to Toronto
- __Rational__: A lot of actions ran based on the timezone setting of the application, these needed to be updated as to not confuse people in the UI or run actions at the wrong time.
- __Commits__ :https://github.com/cds-snc/notification-utils/commit/b571ef2e1c13610b275accf8dbba2d052e3aa7a7
---
- __Change__: Update email templates to remove GOV.UK branding and added Canada branding. 
- __Rational__: This product should not confuse users to think they are receiving messages from a GOV.UK platform.
- __Commits__: https://github.com/cds-snc/notification-utils/commit/0269cf6f9e29014f34fd43660c1425c24e74eeed
---
