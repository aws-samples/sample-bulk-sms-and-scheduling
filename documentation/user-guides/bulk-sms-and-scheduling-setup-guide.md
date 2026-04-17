# Building a CSV-Based Bulk SMS Sender with AWS End User Messaging

## Overview

This guide walks through a serverless solution that lets you upload a CSV file of phone numbers and messages, and have AWS automatically validate, queue, and send SMS to each recipient using AWS End User Messaging. The architecture uses a Dispatcher/Sender pattern with SQS for scalable, concurrency-controlled throughput.

## Prerequisites

- An active AWS account with AWS End User Messaging configured
- A registered origination identity (10DLC number, toll-free number, or short code) that is approved for sending
- Basic familiarity with AWS Lambda, Amazon S3, Amazon SQS, and IAM
- [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html) installed
- AWS CLI configured with credentials
- Python 3.12 runtime for Lambda

## Solution Architecture

The solution uses six AWS services:

- **Amazon S3** — Stores the uploaded CSV file and dispatch logs
- **AWS Lambda (Dispatcher)** — Validates the CSV, resolves message templates, generates campaign context, and writes send jobs to SQS
- **Amazon SQS** — Buffers individual send jobs with retry and dead-letter queue support
- **AWS Lambda (Sender)** — Consumes from SQS and sends SMS with concurrency-controlled throughput
- **AWS End User Messaging (PinpointSMSVoiceV2)** — Delivers the SMS to each recipient
- **Amazon DynamoDB** — Stores reusable message templates (optional)

### How It Works

1. You upload a CSV file to the `incoming/` prefix in S3 (or invoke the Dispatcher directly for scheduled sends)
2. The Dispatcher Lambda validates the CSV upfront — checks headers, phone formats, and message sources
3. The Dispatcher resolves the message for each row using a three-tier priority system
4. Each resolved message is written as an individual job to an SQS queue
5. The Sender Lambda consumes from SQS with reserved concurrency, controlling throughput
6. Each send includes `campaign_name` and `campaign_id` in the Context parameter for analytics
7. Failed sends retry via SQS visibility timeout; permanently failed messages land in a dead-letter queue

![Bulk SMS System Architecture](../architecture/bulk-sms-and-scheduling-system-architecture.png)

## CSV File Format

The Dispatcher auto-detects which format you're using based on the column headers.

### Format A: Per-Row Messages (Priority 1)

Each row has its own fully-written message. No variable substitution is performed.

```csv
phone_number,message
+15551234567,Your appointment is confirmed for April 8 at 3:00 PM.
+15559876543,Your order #4821 has shipped and will arrive by Friday.
```

### Format B: Template Variables with Inline Template (Priority 2)

CSV columns provide variable values. The message template is passed in the invocation payload via `message_template`.

```csv
phone_number,name,appt_date
+15551234567,Tyler,April 10 at 3:00 PM
+15559876543,Jordan,April 12 at 1:00 PM
```

Invocation payload:
```json
{
    "bucket": "my-bucket",
    "key": "scheduled/appointments.csv",
    "campaign_name": "april-reminders",
    "message_template": "Hi {{name}}, your appointment is on {{appt_date}}. Reply STOP to opt out."
}
```

### Format C: Template Variables with Stored DynamoDB Template (Priority 3)

Same CSV format as above, but the template is stored in DynamoDB and referenced by `template_id`.

```json
{
    "bucket": "my-bucket",
    "key": "scheduled/appointments.csv",
    "campaign_name": "april-reminders",
    "template_id": "appointment-reminder-v1"
}
```

### Template Resolution Priority

Messages are resolved in this order — the first match wins:

1. Per-row `message` column in the CSV
2. Inline `message_template` in the request payload (with `{{variable}}` substitution)
3. `template_id` referencing a stored template in DynamoDB

If none of these are provided, the job fails immediately with a clear error. There is no silent default fallback.

### Formatting Requirements

- Phone numbers must be in E.164 format (e.g., `+15551234567`)
- UTF-8 encoding (files with a UTF-8 BOM are handled correctly)
- If message text contains commas, wrap the field in double quotes

## Campaign Context

Every send includes campaign metadata for analytics and reporting:

- `campaign_name` — Human-readable name (required in the invocation payload, or derived from the filename for S3 triggers)
- `campaign_id` — `{campaign_name}-{8-char-uuid}` generated per job execution

These are passed as the `Context` parameter on `send-text-message`, flowing through to CloudWatch and event destinations. Use them to filter delivery rates, failures, and costs per campaign.

## CSV Validation

Before any messages are queued, the Dispatcher performs pre-flight validation:

- CSV has headers (not empty)
- `phone_number` column exists
- At least one message source is configured (per-row column, inline template, or template_id)
- If using a template, all `{{placeholder}}` variables have matching CSV columns
- Per-row: phone numbers match E.164 format, messages are not empty

If validation fails, the entire job is rejected with a detailed error log written to `logs/` in S3. No partial sends occur.

## Quick Start (SAM Deployment)

The included SAM template (`template.yaml`) deploys everything: S3 bucket, Dispatcher Lambda, Sender Lambda, SQS queue, DLQ, DynamoDB template table, IAM roles, S3 event trigger, and EventBridge Scheduler role.

```bash
# Build
sam build

# Deploy (first time — interactive)
sam deploy --guided

# Deploy (subsequent — uses saved config)
sam build && sam deploy
```

Key parameters:

| Parameter | Default | Description |
|---|---|---|
| `StackPrefix` | `BulkSmsSender` | Prefix for resource names — change for multi-stack deploys |
| `OriginationIdentity` | (none) | Your sending phone number or ARN |
| `MessageType` | `TRANSACTIONAL` | `TRANSACTIONAL` or `PROMOTIONAL` |
| `ConfigurationSet` | (none) | Configuration set name for event tracking (optional) |
| `SenderConcurrency` | `20` | Max concurrent Sender Lambda invocations (controls SMS throughput) |
| `MaxRetries` | `2` | Max retry attempts for throttled sends within a single Sender invocation |
| `DlqAlarmEmail` | (none) | Email for DLQ alarm notifications (optional) |

### Multiple Stacks for Different Use Cases

Deploy the same template multiple times with different stack names and prefixes:

```bash
# Marketing — toll-free, promotional, lower throughput
sam deploy --stack-name bulk-sms-marketing \
    --parameter-overrides "StackPrefix=BulkSmsMarketing OriginationIdentity=+18001234567 MessageType=PROMOTIONAL SenderConcurrency=10"

# Transactional — 10DLC, transactional, higher throughput
sam deploy --stack-name bulk-sms-transactional \
    --parameter-overrides "StackPrefix=BulkSmsTransactional OriginationIdentity=+15551234567 MessageType=TRANSACTIONAL SenderConcurrency=50"
```

Each stack gets its own S3 bucket, Lambda functions, SQS queues, and IAM roles — fully isolated.

## Step-by-Step Manual Setup

If you prefer to set up the infrastructure manually instead of using the SAM template, follow these steps.

### Step 1: Create the S3 Bucket

Create an S3 bucket with three prefixes:

- `incoming/` — Where you upload new CSV files (triggers the Dispatcher)
- `scheduled/` — Where you upload CSVs for scheduled sends (no auto-trigger)
- `processed/` — Where the Dispatcher moves files after processing
- `logs/` — Where the Dispatcher writes dispatch and error logs

**Required security configuration:**

1. **Block Public Access** — Enable all four settings
2. **Encryption at rest** — Enable default SSE-KMS encryption with BucketKeyEnabled
3. **Enforce HTTPS** — Add a bucket policy denying `aws:SecureTransport = false`
4. **Enable versioning** — Protects against accidental overwrites and deletes

### Step 2: Create the SQS Queues

Create two SQS queues:

**Send Queue:**
- Visibility timeout: 60 seconds
- Message retention: 1 day
- Redrive policy: max receive count 3, targeting the DLQ

**Dead-Letter Queue (DLQ):**
- Message retention: 14 days

### Step 3: Create the DynamoDB Template Table (Optional)

If you want to use stored templates (Priority 3), create a DynamoDB table:

- Table name: `{StackPrefix}-templates`
- Partition key: `template_id` (String)
- Billing mode: PAY_PER_REQUEST

To create a template:

```bash
aws dynamodb put-item \
    --table-name BulkSmsSender-templates \
    --item '{
        "template_id": {"S": "appointment-reminder-v1"},
        "template_body": {"S": "Hi {{name}}, your appointment is on {{appt_date}}."},
        "description": {"S": "Standard appointment reminder"},
        "required_variables": {"SS": ["name", "appt_date"]},
        "created_at": {"S": "2026-04-17T00:00:00Z"}
    }'
```

### Step 4: Create the Dispatcher Lambda

The Dispatcher (`lambda/dispatcher/app.py`) handles CSV validation, template resolution, campaign context generation, and SQS message writing.

| Setting | Recommended Value |
|---|---|
| Runtime | Python 3.12 |
| Memory | 256 MB |
| Timeout | 5 minutes |
| Architecture | arm64 (Graviton) |
| Handler | `app.handler` |

**Environment variables:**

| Variable | Required | Description |
|---|---|---|
| `ORIGINATION_IDENTITY` | Yes | Your sending phone number or ARN |
| `MESSAGE_TYPE` | No | `TRANSACTIONAL` (default) or `PROMOTIONAL` |
| `CONFIGURATION_SET` | No | Configuration set name for event tracking |
| `SQS_QUEUE_URL` | Yes | URL of the SQS send queue |
| `TEMPLATE_TABLE_NAME` | No | DynamoDB table name (required only if using `template_id`) |

**S3 event trigger configuration:**
- Event type: `s3:ObjectCreated:*`
- Prefix filter: `incoming/`
- Suffix filter: `.csv`

### Step 5: Create the Sender Lambda

The Sender (`lambda/sms_sender/app.py`) consumes from SQS and sends SMS. It's intentionally simple — it receives a fully-resolved message and sends it.

| Setting | Recommended Value |
|---|---|
| Runtime | Python 3.12 |
| Memory | 128 MB |
| Timeout | 30 seconds |
| Architecture | arm64 (Graviton) |
| Handler | `app.handler` |
| Reserved Concurrency | 20 (adjust based on TPS limits) |

**Environment variables:**

| Variable | Required | Description |
|---|---|---|
| `MAX_RETRIES` | No | Max retry attempts for throttled sends (default: `2`) |

**SQS trigger configuration:**
- Batch size: 10
- Function response types: `ReportBatchItemFailures`

### Step 6: Set Up IAM Permissions

**Dispatcher Lambda role:**

| Permission | Resource | Purpose |
|---|---|---|
| `s3:GetObject` | `incoming/*`, `scheduled/*` | Read uploaded CSV |
| `s3:PutObject` | `processed/*`, `logs/*` | Move files, write logs |
| `s3:DeleteObject` | `incoming/*`, `scheduled/*` | Remove from source after move |
| `sqs:SendMessage` | Send Queue ARN | Write send jobs to SQS |
| `dynamodb:GetItem` | Template Table ARN | Fetch stored templates |

**Sender Lambda role:**

| Permission | Resource | Purpose |
|---|---|---|
| `sms-voice:SendTextMessage` | Origination identity ARN | Send SMS |
| `sqs:ReceiveMessage` | Send Queue ARN | Consume messages |
| `sqs:DeleteMessage` | Send Queue ARN | Remove processed messages |
| `sqs:GetQueueAttributes` | Send Queue ARN | Read queue metadata |

In production, scope `sms-voice:SendTextMessage` to your specific origination identity ARN with a condition key:

```json
{
    "Effect": "Allow",
    "Action": "sms-voice:SendTextMessage",
    "Resource": "arn:aws:sms-voice:us-west-2:123456789012:phone-number/phone-abcdef1234567890abcdef1234567890",
    "Condition": {
        "StringEquals": {
            "sms-voice:OriginationIdentity": "+15551234567"
        }
    }
}
```

### Step 7: Test

1. Upload a small CSV (2–3 numbers you control) to `incoming/`
2. Check CloudWatch Logs for the Dispatcher Lambda — confirm validation passed and messages were queued
3. Check CloudWatch Logs for the Sender Lambda — confirm SMS was sent with campaign context
4. Check the `logs/` prefix in S3 for the dispatch log
5. Confirm SMS delivery on your test devices
6. Verify the CSV file was moved to `processed/`

## Two Ways to Send

### Immediate Send (S3 Trigger)

Upload a CSV to the `incoming/` prefix and it processes immediately:

```bash
aws s3 cp my-campaign.csv s3://YOUR-BUCKET/incoming/my-campaign.csv
```

When triggered by S3, the `campaign_name` is derived from the filename (e.g. `my-campaign`).

### Scheduled Send (EventBridge Scheduler)

Upload a CSV to `scheduled/` (no auto-trigger), then create a one-time schedule:

```bash
# 1. Upload the CSV
aws s3 cp my-campaign.csv s3://YOUR-BUCKET/scheduled/my-campaign.csv

# 2. Create a schedule
aws scheduler create-schedule \
    --name "april-campaign" \
    --schedule-expression "at(2026-04-20T10:00:00)" \
    --schedule-expression-timezone "America/Los_Angeles" \
    --flexible-time-window Mode=OFF \
    --action-after-completion DELETE \
    --target '{
        "Arn": "YOUR-DISPATCHER-ARN",
        "RoleArn": "YOUR-SCHEDULER-ROLE-ARN",
        "Input": "{\"bucket\":\"YOUR-BUCKET\",\"key\":\"scheduled/my-campaign.csv\",\"campaign_name\":\"april-campaign\"}"
    }' \
    --region us-west-2
```

For direct invocation, `campaign_name` is required in the payload.

## Scheduling Options

The SAM template deploys EventBridge Scheduler support out of the box (IAM role included). The other options below require additional infrastructure.

### Option 1: Amazon EventBridge Scheduler (Included in Template)

Already deployed with the stack. Upload CSVs to `scheduled/`, create a schedule pointing to the file, and it sends at the specified time.

**Advantages:**
- Native time zone support — schedule in your recipients' local time
- One-time and recurring schedules (cron or rate-based)
- Schedules auto-delete after execution (`--action-after-completion DELETE`)
- Very low cost (free tier covers 14 million invocations/month)

### Option 2: Amazon DynamoDB Scheduling Table

Best for managing many campaigns with cancel/reschedule capability. Requires a DynamoDB table and a poller Lambda.

**How it works:**
1. A DynamoDB table (`ScheduledCampaigns`) stores campaign records with `campaign_id`, `s3_key`, `scheduled_time`, and `status`
2. A poller Lambda runs on a 1-minute EventBridge cron schedule
3. The poller queries for records where `scheduled_time <= now` and `status = pending`
4. For each match, it invokes the Dispatcher Lambda with the S3 bucket, key, and campaign_name

### Option 3: AWS Step Functions with Wait State

Best for complex workflows with approval steps and visual designer.

**Workflow:**
```
S3 Upload → Read Metadata → Wait (until send-at) → Invoke Dispatcher → Report
```

## Throttling and Throughput Control

SMS throughput is controlled by the `SenderConcurrency` parameter — the reserved concurrency on the Sender Lambda. Each Sender invocation processes up to 10 messages from SQS.

| SenderConcurrency | Approx. Throughput | Use Case |
|---|---|---|
| 5 | ~25 msg/sec | Low-volume, conservative |
| 20 | ~100 msg/sec | Standard workloads |
| 50 | ~250 msg/sec | High-volume campaigns |

Adjust based on your account's SMS rate limits. No code changes needed — just update the parameter and redeploy.

**AWS End User Messaging TPS limits by origination type:**

| Origination Type | Typical TPS |
|---|---|
| 10DLC (low-vetting score) | 1–4 TPS |
| 10DLC (high-vetting score) | Up to 75 TPS |
| Toll-free | 3 TPS |
| Short code | 100 TPS |

## Failed Message Handling

Messages that fail after 3 SQS delivery attempts land in the dead-letter queue (DLQ). If you provided a `DlqAlarmEmail` parameter, a CloudWatch alarm triggers an SNS notification when messages appear in the DLQ.

To inspect failed messages:

```bash
# Check DLQ depth
aws sqs get-queue-attributes \
    --queue-url YOUR-DLQ-URL \
    --attribute-names ApproximateNumberOfMessages

# Receive and inspect failed messages
aws sqs receive-message \
    --queue-url YOUR-DLQ-URL \
    --max-number-of-messages 10
```

## Error Handling

- The Dispatcher validates the entire CSV before queuing any messages — no partial sends on validation failure
- The Sender uses SQS partial batch failure reporting — only failed messages return to the queue
- Throttled sends are retried with exponential backoff within the Sender invocation
- Permanently failed messages land in the DLQ after 3 SQS delivery attempts
- Dispatch logs and validation error logs are written to `logs/` in S3

## Opt-Out Compliance

- AWS End User Messaging automatically handles STOP/HELP keyword responses at the carrier level
- You are responsible for maintaining your own opt-out list and filtering your CSV before uploading
- Do not send to numbers that have previously opted out
- Include opt-out instructions in your message content where required by regulation

## Security

### S3 Bucket Security

- Block Public Access enabled (all four settings)
- Default encryption at rest (SSE-KMS with BucketKeyEnabled)
- Bucket policy enforces HTTPS-only access
- Versioning enabled to protect against accidental deletes
- Consider enabling MFA Delete for production buckets
- Enable server access logging or CloudTrail data events for audit

### Lambda Security

- Least-privilege execution roles — Dispatcher and Sender have separate, scoped roles
- Sender Lambda has reserved concurrency to prevent runaway invocations
- Set appropriate timeout and memory limits
- Enable AWS X-Ray tracing for debugging and performance monitoring

### SQS Security

- Send queue has a redrive policy limiting retries to 3 attempts
- DLQ retains failed messages for 14 days for investigation
- Optional CloudWatch alarm on DLQ message count

### DynamoDB Security (Template Table)

- Encryption at rest enabled by default
- Dispatcher role has read-only access (`dynamodb:GetItem`)
- PAY_PER_REQUEST billing mode — no capacity planning needed

### End User Messaging Security

- Scope `SendTextMessage` to a specific origination identity ARN with a condition key
- Use a configuration set to track delivery events
- Monitor spend with SMS spend limits in the console
- Use `TRANSACTIONAL` for time-sensitive messages and `PROMOTIONAL` for marketing

### EventBridge Scheduler Security

- Dedicated IAM role scoped to invoke only the Dispatcher Lambda
- Use `ActionAfterCompletion: DELETE` for one-time schedules
- Set `FlexibleTimeWindow` to `OFF` for time-sensitive sends

## Data Classification and Handling

| Data Element | Classification | Storage Location | Protection |
|---|---|---|---|
| Phone numbers (E.164) | PII | S3 (CSV), SQS (in transit), CloudWatch Logs | Encryption at rest, HTTPS in transit |
| SMS message content | PII / Sensitive | S3 (CSV), SQS (in transit), CloudWatch Logs | Encryption at rest, HTTPS in transit |
| Campaign metadata | Operational | SQS, CloudWatch, event destinations | Encryption at rest |
| Message templates | Configuration | DynamoDB | Encryption at rest |
| Send results / Message IDs | Operational | S3 (log files), CloudWatch Logs | Encryption at rest |

**Handling procedures:**
- Set S3 lifecycle policies to expire processed files and logs after your retention period
- SQS messages are retained for 1 day (send queue) or 14 days (DLQ)
- Restrict access to the S3 bucket, SQS queues, and CloudWatch log groups to authorized personnel
- Do not log full message content to CloudWatch in production

## Cost Considerations

| Component | Pricing Model |
|---|---|
| SMS messages | Per message segment, varies by destination country |
| Lambda (Dispatcher) | Per invocation + duration (free tier: 1M requests/month) |
| Lambda (Sender) | Per invocation + duration |
| S3 | Per GB stored + per request (negligible for CSV files) |
| SQS | Per million requests (free tier: 1M requests/month) |
| DynamoDB | Per read/write request (negligible for template lookups) |
| EventBridge Scheduler | Free tier covers 14M invocations/month |
| CloudWatch Alarms | $0.10/alarm/month |
| SNS (DLQ notifications) | Per notification |

The dominant cost will be the SMS messages themselves. The infrastructure costs are minimal.

## Next Steps

1. Deploy the SAM template with `sam build && sam deploy --guided`
2. Test with a small CSV of numbers you control
3. Create stored templates in DynamoDB for reusable message formats
4. Set up EventBridge Scheduler for timed sends
5. Configure the `DlqAlarmEmail` parameter for failure notifications
6. Adjust `SenderConcurrency` based on your TPS limits and volume needs
7. Build a simple upload interface if needed (API Gateway + S3 presigned URLs)

For questions about origination identity setup, 10DLC registration, or sending limits, refer to the [AWS End User Messaging documentation](https://docs.aws.amazon.com/sms-voice/latest/userguide/) or contact your AWS account team.
