# CSV Bulk SMS Sender and Scheduler

A serverless solution for sending bulk SMS messages from a CSV file using AWS End User Messaging. Upload a CSV of phone numbers and messages to Amazon S3, and AWS Lambda automatically sends SMS to each recipient. Includes multiple scheduling options for timed sends.

## Features

- **CSV-driven sending** — Upload a CSV and SMS messages are sent automatically
- **Flexible CSV formats** — Same message to all, unique per recipient, or template variables with `{{placeholder}}` support
- **Scheduling options** — Immediate send, EventBridge Scheduler, DynamoDB polling, or Step Functions workflows
- **Automatic logging** — Per-row send results written to S3 as plain-text log files
- **File lifecycle management** — Processed CSVs are moved from `incoming/` to `processed/` automatically
- **Throttle control** — Configurable delay between sends to respect TPS limits

## Architecture

```
                         Immediate Send
┌──────────┐     ┌──────────────┐     ┌─────────────────────────┐
│  CSV      │────▶│  Amazon S3   │────▶│  AWS Lambda             │
│  Upload   │     │  incoming/   │     │  (bulk_sms_sender)      │
└──────────┘     └──────────────┘     └────────┬────────────────┘
                                               │
                       Scheduled Send          │
┌──────────┐     ┌──────────────┐              │
│  CSV      │────▶│  Amazon S3   │              │
│  Upload   │     │  scheduled/  │              │
└──────────┘     └──────────────┘              │
                                               │
┌──────────────────────┐                       │
│  EventBridge         │───────────────────────┘
│  Scheduler (at time) │
└──────────────────────┘
                                               │
                                    ┌──────────▼──────────────┐
                                    │  AWS End User Messaging  │
                                    │  (PinpointSMSVoiceV2)    │
                                    └──────────┬──────────────┘
                                               │
                                    ┌──────────▼──────────────┐
                                    │  SMS delivered to        │
                                    │  recipients              │
                                    └─────────────────────────┘
```

## Prerequisites

- An active AWS account with AWS End User Messaging configured
- A registered origination identity (10DLC, toll-free, or short code) approved for sending
- [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html) installed
- AWS CLI configured with credentials
- Python 3.12 runtime for Lambda

## Quick Start (SAM Deployment)

The included SAM template (`template.yaml`) deploys everything you need: S3 bucket, Lambda function, IAM roles, S3 event trigger, and an EventBridge Scheduler role for scheduled sends.

```bash
# Build
sam build

# Deploy (first time — interactive)
sam deploy --guided

# Deploy (subsequent — uses saved config)
sam build && sam deploy
```

The deploy will prompt for parameters. Key ones:

| Parameter | Default | Description |
|---|---|---|
| `StackPrefix` | `BulkSmsSender` | Prefix for resource names — change for multi-stack deploys |
| `OriginationIdentity` | (none) | Your sending phone number or ARN |
| `DefaultMessage` | (empty) | Default message body for phone-only CSVs |
| `MessageType` | `TRANSACTIONAL` | `TRANSACTIONAL` or `PROMOTIONAL` |

After deployment, the stack outputs give you the bucket name, Lambda ARN, scheduler role ARN, and example commands.

### Multiple stacks for different use cases

Deploy the same template multiple times with different stack names and prefixes:

```bash
# Marketing — toll-free, promotional
sam deploy --stack-name bulk-sms-marketing \
    --parameter-overrides "StackPrefix=BulkSmsMarketing OriginationIdentity=+18001234567 MessageType=PROMOTIONAL"

# Transactional — 10DLC, transactional
sam deploy --stack-name bulk-sms-transactional \
    --parameter-overrides "StackPrefix=BulkSmsTransactional OriginationIdentity=+15551234567 MessageType=TRANSACTIONAL"
```

Each stack gets its own S3 bucket, Lambda function, and IAM roles — fully isolated.

## Two Ways to Send

The Lambda supports two invocation modes simultaneously:

### Immediate send (S3 trigger)

Upload a CSV to the `incoming/` prefix and it sends immediately:

```bash
aws s3 cp my-campaign.csv s3://YOUR-BUCKET/incoming/my-campaign.csv
```

The S3 event trigger fires the Lambda automatically. After processing, the CSV moves to `processed/` and a log file is written to `logs/`.

### Scheduled send (EventBridge Scheduler)

Upload a CSV to the `scheduled/` prefix (no auto-trigger), then create a one-time schedule:

```bash
# 1. Upload the CSV (won't trigger Lambda — no event on scheduled/ prefix)
aws s3 cp my-campaign.csv s3://YOUR-BUCKET/scheduled/my-campaign.csv

# 2. Create a schedule to send at a specific date/time
aws scheduler create-schedule \
    --name "april-campaign" \
    --schedule-expression "at(2026-04-20T10:00:00)" \
    --schedule-expression-timezone "America/Los_Angeles" \
    --flexible-time-window Mode=OFF \
    --action-after-completion DELETE \
    --target '{
        "Arn": "YOUR-LAMBDA-ARN",
        "RoleArn": "YOUR-SCHEDULER-ROLE-ARN",
        "Input": "{\"bucket\":\"YOUR-BUCKET\",\"key\":\"scheduled/my-campaign.csv\"}"
    }' \
    --region us-west-2
```

At the scheduled time, EventBridge Scheduler invokes the Lambda directly with the bucket and key. The schedule auto-deletes after execution.

The stack outputs include a pre-filled `ScheduleCommand` with your actual ARNs and bucket name — just update the date/time and filename.

## CSV Formats

### Same message to all recipients
```csv
phone_number
+15551234567
+15559876543
```
Set the `DEFAULT_MESSAGE` environment variable with your message body.

### Unique message per recipient
```csv
phone_number,message
+15551234567,Your appointment is confirmed for April 8.
+15559876543,Your order #4821 has shipped.
```

### Template variables
```csv
phone_number,name,appt_date
+15551234567,Tyler,April 10 at 3:00 PM
+15559876543,Jordan,April 12 at 1:00 PM
```
Set `DEFAULT_MESSAGE` to: `Hi {{name}}, your appointment is on {{appt_date}}.`

**Note:** Placeholders are only replaced when the CSV contains a matching column. If your `DEFAULT_MESSAGE` includes `{{name}}` but the CSV only has a `phone_number` column, the literal text `{{name}}` will appear in the delivered message. Use a plain `DEFAULT_MESSAGE` (no placeholders) when sending the same message to all recipients.

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `ORIGINATION_IDENTITY` | Yes | Sending phone number or ARN |
| `DEFAULT_MESSAGE` | Conditional | Default message body (required when CSV has no `message` column) |
| `MESSAGE_TYPE` | No | `TRANSACTIONAL` (default) or `PROMOTIONAL` |
| `CONFIGURATION_SET` | No | Configuration set name for event tracking |
| `SEND_DELAY_MS` | No | Milliseconds between sends (default: `50`) |
| `MAX_RETRIES` | No | Max retry attempts for throttled sends (default: `3`). Uses exponential backoff (2s, 4s, 8s). |

## IAM Permissions Required

| Permission | Resource | Purpose |
|---|---|---|
| `s3:GetObject` | `arn:aws:s3:::YOUR-BUCKET/incoming/*` | Read uploaded CSV |
| `s3:PutObject` | `arn:aws:s3:::YOUR-BUCKET/processed/*`, `arn:aws:s3:::YOUR-BUCKET/logs/*` | Move files, write logs |
| `s3:DeleteObject` | `arn:aws:s3:::YOUR-BUCKET/incoming/*` | Remove from incoming after move |
| `sms-voice:SendTextMessage` | `arn:aws:us-east-1:123456789012:phone-number/phone-abcdef1234567890abcdef1234567890` | Send SMS via a specific origination identity |

Scope `sms-voice:SendTextMessage` to your specific origination identity ARN. Add a condition key to further restrict by origination identity:

```json
{
    "Effect": "Allow",
    "Action": "sms-voice:SendTextMessage",
    "Resource": "arn:aws:sms-voice:us-east-1:123456789012:phone-number/phone-abcdef1234567890abcdef1234567890",
    "Condition": {
        "StringEquals": {
            "sms-voice:OriginationIdentity": "+15551234567"
        }
    }
}
```

## Scheduling Options

The SAM template deploys EventBridge Scheduler support out of the box (IAM role included). The other options below require additional infrastructure.

### Option 1: Amazon EventBridge Scheduler (included in template)

Already deployed with the stack. Upload CSVs to `scheduled/`, create a schedule pointing to the file, and it sends at the specified time. See "Scheduled send" above for usage.

Advantages:
- Native time zone support — schedule in your recipients' local time
- One-time and recurring schedules (cron or rate-based)
- Schedules auto-delete after execution (`--action-after-completion DELETE`)
- Very low cost (free tier covers 14 million invocations/month)

### Option 2: Amazon DynamoDB Scheduling Table

Best for managing many campaigns with cancel/reschedule capability. Requires a DynamoDB table and a poller Lambda. See the [full documentation](documentation/user-guides/bulk-sms-and-scheduling-setup-guide.md) for setup details.

### Option 3: AWS Step Functions

Best for complex workflows with approval steps and visual designer. Requires a Step Functions state machine. See the [full documentation](documentation/user-guides/bulk-sms-and-scheduling-setup-guide.md) for setup details.

## Security

### S3 Bucket Security

- Enable Block Public Access on the S3 bucket
- Enable default encryption (SSE-S3 or SSE-KMS) for encryption at rest
- Add a bucket policy to enforce HTTPS-only access (deny `aws:SecureTransport = false`)
- Enable S3 server access logging or AWS CloudTrail data events
- Enable versioning to protect against accidental deletes
- Consider enabling MFA Delete for production buckets

### IAM and Access Control

- Scope all S3 permissions to the specific bucket ARN
- Scope `sms-voice:SendTextMessage` to your origination identity ARN with a condition key (see IAM section above)
- Use least-privilege IAM roles — grant only the permissions listed in the IAM table
- Review IAM policies periodically and remove unused permissions

### Data Protection

- Phone numbers and message content are PII — treat them accordingly
- Enable encryption at rest on S3 (SSE-S3 or SSE-KMS) and Lambda environment variables (KMS)
- All AWS SDK calls use HTTPS (TLS) by default for encryption in transit
- Enforce HTTPS-only access to S3 via bucket policy
- Consider using AWS KMS customer managed keys for sensitive workloads and rotate keys annually

### Opt-Out Compliance

- AWS End User Messaging automatically handles STOP/HELP keyword responses at the carrier level
- Filter opt-out numbers before uploading your CSV
- Include opt-out instructions in message content where required by regulation

## License

This project is licensed under the MIT-0 License. See the [LICENSE](LICENSE) file.
