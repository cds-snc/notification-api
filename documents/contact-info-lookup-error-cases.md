# Contact information lookup error cases

|                                  Error                                 | Retryable? |          How to Handle         | Notification Status |
|:----------------------------------------------------------------------:|:----------:|:------------------------------:|:-------------------:|
| Consumer calls endpoint without required information (participant ID)  | No         | Respond to consumer with a 400 |                     |
| MPI is down/times out                                                  | Yes        | Retry                          | Technical Failure   |
| VA Profile is down/times out                                           | Yes        |                                | Technical Failure   |
| Unauthorized to talk to MPI                                            | No         |                                | Permanent Failure   |
| Unauthorized to talk to VA Profile                                     | No         |                                | Permanent Failure   |
| MPI doesn’t recognize Participant ID                                   | No         |                                | Permanent Failure   |
| VA Profile doesn’t recognize Vet360 ID                                 | No         |                                | Permanent Failure   |
| VA Profile returns invalid contact information                         | No         | alerting                       | Permanent Failure   |
| VA Profile returns no contact information                              | No         |                                | Permanent Failure   |
| VA Profile returns contact information that we are not allowed to send | No         |                                | Permanent Failure   |
| Service has exceeded rate limit                                        | No         | Respond with 429               |                     |
| Daily message limit has been exceeded                                  | No         | Respond with 429               |                     |