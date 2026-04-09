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

See the [full documentation](documentation/user-guides/bulk-sms-and-scheduling-setup-guide.md) for detailed scheduling options:

1. **Amazon EventBridge Scheduler** (recommended) — Simple, low-cost, native time zone support
2. **Amazon DynamoDB Scheduling Table** — Campaign management with cancel/reschedule capability
3. **AWS Step Functions** — Complex workflows with approval steps and visual designer

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
