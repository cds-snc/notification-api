# Data Flow

These diagrams show where the data for our notifications exist and what tasks move it along. Most tasks are run asyncronously by adding to a SQS queue and having our celery workers pick them up. Some tasks (particularly ones handling errors) are scheduled to run at certain intervals.

We assume emails are being sent, but the flows for sms are similar (with "save_smss" replacing "save_emails", and so on).

## POST to /email or /sms

### Happy path

```mermaid
    sequenceDiagram
    
    participant internet
    participant redis inbox
    participant redis inflight
    participant RDS
    participant SES

    internet ->> redis inbox: POST /email
    redis inbox ->> redis inflight: beat-inbox-*
    redis inflight ->> RDS: save_emails
    RDS ->> SES: deliver_email
```

### Error saving to database

```mermaid
    sequenceDiagram
    
    participant internet
    participant redis inbox
    participant redis inflight
    participant RDS

    internet ->> redis inbox: POST /email
    redis inbox ->> redis inflight: beat-inbox-*
    redis inflight --x RDS: save_emails
    
    redis inflight ->> redis inbox: in-flight-to-inbox
```

### Error sending to SES

```mermaid
    sequenceDiagram
        
    participant redis inflight
    participant RDS
    participant SES

    redis inflight ->> RDS: save_emails
    RDS --x SES: deliver_email
    RDS ->> SES: replay-created-notifications, deliver_email
```

## POST to /bulk

### Happy path

```mermaid
    sequenceDiagram
    
    participant internet
    participant RDS
    participant SES

    internet ->> RDS: POST /bulk (job)
    RDS ->> RDS: process_job, save_emails (notifications)
    RDS ->> SES: deliver_email
    RDS ->> SES: deliver_email
```

### process_job interrupted

```mermaid
    sequenceDiagram
    
    participant internet
    participant RDS
    participant SES

    internet ->> RDS: POST /bulk (job)
    RDS --x RDS: process_job, save_emails (notifications)

    RDS ->> RDS: check_job_status, process-incomplete-jobs, save_emails (notifications)
    RDS ->> SES: deliver_email
    RDS ->> SES: deliver_email
```

### Error sending to SES

```mermaid
    sequenceDiagram
    
    participant internet
    participant RDS
    participant SES

    internet ->> RDS: POST /bulk (job)
    RDS ->> RDS: process_job, save_emails (notifications)
    RDS ->> SES: deliver_email
    RDS --x SES: deliver_email
    RDS ->> SES: replay-created-notifications, deliver_email
```