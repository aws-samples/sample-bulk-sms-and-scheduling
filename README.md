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
┌──────────┐     ┌──────────────┐     ┌─────────────────────────┐
│  CSV      │────▶│  Amazon S3   │────▶│  AWS Lambda             │
│  Upload   │     │  incoming/   │     │  (bulk_sms_sender)      │
└──────────┘     └──────────────┘     └────────┬────────────────┘
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
- AWS CLI or AWS Console access
- Python 3.12 runtime for Lambda

## Quick Start

1. Create an S3 bucket with `incoming/`, `processed/`, and `logs/` prefixes
2. Deploy the Lambda function from `lambda/bulk_sms_sender/app.py`
3. Configure environment variables (see below)
4. Set up an S3 event trigger on `incoming/*.csv`
5. Upload a CSV and watch it send

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

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `ORIGINATION_IDENTITY` | Yes | Sending phone number or ARN |
| `DEFAULT_MESSAGE` | Conditional | Default message body (required when CSV has no `message` column) |
| `MESSAGE_TYPE` | No | `TRANSACTIONAL` (default) or `PROMOTIONAL` |
| `CONFIGURATION_SET` | No | Configuration set name for event tracking |
| `SEND_DELAY_MS` | No | Milliseconds between sends (default: `50`) |

## IAM Permissions Required

| Permission | Resource | Purpose |
|---|---|---|
| `s3:GetObject` | `bucket/incoming/*` | Read uploaded CSV |
| `s3:PutObject` | `bucket/processed/*`, `bucket/logs/*` | Move files, write logs |
| `s3:DeleteObject` | `bucket/incoming/*` | Remove from incoming after move |
| `sms-voice:SendTextMessage` | `*` | Send SMS |

## Scheduling Options

See the [full documentation](documentation/user-guides/bulk-sms-and-scheduling-setup-guide.md) for detailed scheduling options:

1. **Amazon EventBridge Scheduler** (recommended) — Simple, low-cost, native time zone support
2. **DynamoDB Scheduling Table** — Campaign management with cancel/reschedule capability
3. **AWS Step Functions** — Complex workflows with approval steps and visual designer

## Security

- Scope S3 permissions to specific bucket ARNs
- Use least-privilege IAM roles
- Filter opt-out numbers before uploading
- Include opt-out instructions in message content

## License

This project is licensed under the MIT-0 License. See the [LICENSE](LICENSE) file.
