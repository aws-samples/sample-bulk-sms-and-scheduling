# Building a CSV-Based Bulk SMS Sender with AWS End User Messaging

## Overview

This guide walks through how to build a serverless solution that lets you upload a CSV file of phone numbers and messages, and have AWS automatically send SMS to each recipient using AWS End User Messaging. We also cover multiple options for scheduling sends so messages go out at the right time.

## Prerequisites

- An active AWS account with AWS End User Messaging configured
- A registered origination identity (10DLC number, toll-free number, or short code) that is approved for sending
- Basic familiarity with AWS Lambda, Amazon S3, and IAM
- AWS CLI or AWS Console access

## Solution Architecture

The core solution uses three AWS services:

- **Amazon S3** — Stores the uploaded CSV file
- **AWS Lambda** — Reads the CSV and sends each message via the SMS API
- **AWS End User Messaging (PinpointSMSVoiceV2)** — Delivers the SMS to each recipient

### How It Works

1. You upload a CSV file to a designated S3 bucket
2. The upload triggers a Lambda function
3. Lambda reads the CSV, iterates through each row, and calls the `SendTextMessage` API for each phone number
4. Successes and failures are logged to Amazon CloudWatch

## CSV File Format

The Lambda function (`csv-bulk-sms-sender/lambda/bulk_sms_sender/app.py`) auto-detects which format you're using based on the column headers.

### Option A: Same Message to All Recipients

If every recipient gets the same message, include only phone numbers. The message body comes from the `DEFAULT_MESSAGE` environment variable on the Lambda.

```csv
phone_number
+15551234567
+15559876543
+15551112222
```

### Option B: Unique Message Per Recipient

If each recipient gets a different message, include both columns:

```csv
phone_number,message
+15551234567,Your appointment is confirmed for April 8 at 3:00 PM.
+15559876543,Your order #4821 has shipped and will arrive by Friday.
+15551112222,Your verification code is 482910. It expires in 10 minutes.
```

### Option C: Template Variables (Personalized Messages from a Template)

Add any extra columns beyond `phone_number` and `message` — they become template variables that replace `{{column_name}}` placeholders in the message body. This works with both the `DEFAULT_MESSAGE` environment variable and the inline `message` column.

```csv
phone_number,name,appt_date
+15551234567,Tyler,April 10 at 3:00 PM
+15559876543,Jordan,April 12 at 1:00 PM
+15551112222,Alex,April 15 at 9:00 AM
```

With `DEFAULT_MESSAGE` set to:

```
Hi {{name}}, your appointment is on {{appt_date}}. Reply STOP to opt out.
```

This sends `"Hi Tyler, your appointment is on April 10 at 3:00 PM..."` to the first number, and so on.

**Formatting requirements:**
- Phone numbers must be in E.164 format (e.g., `+15551234567`)
- UTF-8 encoding
- If message text contains commas, wrap the field in double quotes

## Step-by-Step Setup

### Step 1: Create the S3 Bucket

Create an S3 bucket to receive your CSV uploads. We recommend creating three prefixes (folders) inside the bucket:

- `incoming/` — Where you upload new CSV files
- `processed/` — Where Lambda moves files after processing
- `logs/` — Where Lambda writes a plain-text log file for each send

This keeps your bucket organized and prevents reprocessing.

### Step 2: Create the Lambda Function

A reference implementation is provided at `lambda/bulk_sms_sender/app.py`. You can deploy this directly or use it as a starting point.

Create a Lambda function with the following configuration:

| Setting | Recommended Value |
|---|---|
| Runtime | Python 3.12 |
| Memory | 256 MB |
| Timeout | 5 minutes (increase for larger files) |
| Architecture | arm64 (Graviton, lower cost) |
| Handler | `app.handler` |

**Environment variables:**

| Variable | Required | Description |
|---|---|---|
| `ORIGINATION_IDENTITY` | Yes | Your sending phone number or ARN (e.g., `+15551234567`) |
| `DEFAULT_MESSAGE` | Conditional | Default message body — required when your CSV has no `message` column. Supports `{{variable}}` placeholders. |
| `MESSAGE_TYPE` | No | `TRANSACTIONAL` (default) or `PROMOTIONAL` |
| `CONFIGURATION_SET` | No | Configuration set name for event tracking and delivery metrics. If omitted, no configuration set is used. |
| `SEND_DELAY_MS` | No | Milliseconds to wait between each send (default: `50`). Adjust based on your TPS limit. |

**What the function does:**

1. Receives the S3 event notification containing the bucket name and file key
2. Downloads the CSV file from S3 and parses it in memory
3. Auto-detects the CSV format (phone-only, phone+message, or template variables)
4. For each row, substitutes any `{{variable}}` placeholders with values from extra CSV columns
5. Calls the `SendTextMessage` API with the phone number, resolved message body, origination identity, and configuration set
6. Logs the result (message ID on success, error details on failure)
7. After processing all rows, writes a plain-text log file to the `logs/` prefix in S3 (e.g., `logs/april-campaign-20260408-150032.txt`)
8. Moves the CSV file from `incoming/` to `processed/`

**S3 log file format:**

Each send produces a log file in `logs/` with a summary and per-row details:

```
CSV Bulk SMS Send Log
Source file: s3://my-bucket/incoming/april-campaign.csv
Timestamp:   2026-04-08T15:00:32+00:00

Total: 3  |  Sent: 2  |  Failed: 1

--- Per-Row Details ---
Row 1 | SENT | +15551234567 | MessageId: abc123-def456
Row 2 | SENT | +15559876543 | MessageId: ghi789-jkl012
Row 3 | FAILED | +15551112222 | ValidationException: Invalid phone number format

--- Errors ---
+15551112222: ValidationException: Invalid phone number format
```

**Tip:** For very large files (100,000+ rows), consider modifying the function to stream the CSV directly from S3 using the SDK's streaming response instead of reading the entire file into memory.

### Step 3: Configure the S3 Event Trigger

Set up an S3 event notification on your bucket:

- **Event type:** `s3:ObjectCreated:*`
- **Prefix filter:** `incoming/`
- **Suffix filter:** `.csv`
- **Destination:** Your Lambda function

This ensures Lambda only fires when a new CSV file lands in the `incoming/` folder.

### Step 4: Set Up IAM Permissions

Your Lambda execution role needs the following permissions:

| Permission | Resource | Purpose |
|---|---|---|
| `s3:GetObject` | Your S3 bucket/incoming/* | Read the uploaded CSV |
| `s3:PutObject` | Your S3 bucket/processed/* and logs/* | Move processed files and write log files |
| `s3:DeleteObject` | Your S3 bucket/incoming/* | Remove file from incoming after move |
| `sms-voice:SendTextMessage` | * | Send SMS via End User Messaging |
| `logs:CreateLogGroup` | Lambda log group | CloudWatch logging |
| `logs:CreateLogStream` | Lambda log group | CloudWatch logging |
| `logs:PutLogEvents` | Lambda log group | CloudWatch logging |

**Security best practice:** Scope the S3 permissions to only the specific bucket ARN, and consider adding a condition key to restrict `SendTextMessage` to your specific origination identity if you have multiple.

### Step 5: Test

1. Upload a small CSV (2–3 numbers you control) to `incoming/`
2. Check CloudWatch Logs for the Lambda execution
3. Check the `logs/` prefix in S3 for the plain-text log file with per-row results
4. Confirm SMS delivery on your test devices
5. Verify the CSV file was moved to `processed/`

---

## Scheduling Options

The basic setup above sends messages immediately when a file is uploaded. Most production use cases require the ability to schedule sends for a specific date and time. Below are three options, ranging from simple to full-featured.

---

### Option 1: Amazon EventBridge Scheduler (Recommended)

**Best for:** Most use cases. Simple, low-cost, native time zone support.

**How it works:**

Instead of triggering Lambda directly from S3, you decouple the upload from the send. The CSV is uploaded to S3 at any time, and a one-time schedule in Amazon EventBridge Scheduler invokes the Lambda at the desired send time.

**Setup:**

1. Upload the CSV to S3 (remove the automatic S3→Lambda trigger, or use a different prefix like `scheduled/`)
2. Create an EventBridge Scheduler schedule that invokes your Lambda function at the desired date/time, passing the S3 bucket and key as input
3. At the scheduled time, EventBridge invokes Lambda, which reads the file and sends

**Creating a schedule (AWS CLI example):**

```bash
aws scheduler create-schedule \
    --name "april-campaign-send" \
    --schedule-expression "at(2026-04-08T10:00:00)" \
    --schedule-expression-timezone "America/New_York" \
    --flexible-time-window '{"Mode": "OFF"}' \
    --target '{
        "Arn": "arn:aws:lambda:us-east-1:123456789012:function:BulkSmsSender",
        "RoleArn": "arn:aws:iam::123456789012:role/EventBridgeSchedulerRole",
        "Input": "{\"bucket\": \"my-bulk-sms-uploads\", \"key\": \"scheduled/april-campaign.csv\"}"
    }'
```

**Advantages:**
- Native time zone support — schedule in your recipients' local time
- One-time and recurring schedules (cron or rate-based)
- No additional infrastructure required
- Very low cost (free tier covers 14 million invocations/month)
- Schedules auto-delete after execution (configurable)

**Considerations:**
- Schedule creation is a separate step from file upload (can be automated via API Gateway + Lambda)
- For a self-service experience, you would build a small frontend or API that accepts the file + desired send time and creates both the S3 object and the schedule

---

### Option 2: DynamoDB Scheduling Table

**Best for:** Customers who need to manage many scheduled campaigns with the ability to view, cancel, or reschedule pending sends.

**How it works:**

A DynamoDB table acts as a scheduling ledger. When a CSV is uploaded, a record is written with the desired send time. A poller Lambda runs every minute and checks for any campaigns that are due.

**Setup:**

1. Create a DynamoDB table (`ScheduledCampaigns`) with fields:
   - `campaign_id` (partition key)
   - `s3_key` — path to the CSV in S3
   - `scheduled_time` — ISO 8601 timestamp for when to send
   - `status` — `pending`, `sending`, `sent`, or `failed`
   - `created_at` — when the campaign was scheduled

2. When a CSV is uploaded to S3, a Lambda function fires and writes a record to DynamoDB with the S3 key and desired send time (passed as S3 object metadata or via an API call)

3. A separate "poller" Lambda runs on a 1-minute EventBridge cron schedule. It queries DynamoDB for records where `scheduled_time <= now` and `status = pending`

4. For each matching record, the poller updates the status to `sending`, invokes the SMS-sending Lambda, and updates the status to `sent` (or `failed`) when complete

**Advantages:**
- Full visibility into all scheduled, in-progress, and completed campaigns
- Easy to cancel a pending send (just update status to `cancelled`)
- Easy to reschedule (update the `scheduled_time`)
- Can build a dashboard or API on top of the DynamoDB table
- Supports concurrent campaigns with independent schedules

**Considerations:**
- More moving parts (two Lambda functions + DynamoDB table)
- 1-minute polling granularity (sends may fire up to 60 seconds after the scheduled time)
- DynamoDB costs are minimal but non-zero

---

### Option 3: AWS Step Functions with Wait State

**Best for:** Customers who want scheduling as part of a larger workflow (e.g., approval → schedule → send → report), or who prefer a visual workflow designer.

**How it works:**

An S3 upload triggers a Step Functions state machine. The state machine reads the desired send time from the file metadata, pauses using a `Wait` state until that time arrives, then invokes the sending Lambda.

**Workflow:**

```
┌─────────────┐     ┌──────────────┐     ┌──────────┐     ┌─────────────┐     ┌──────────┐
│  S3 Upload  │────▶│ Read Metadata│────▶│   Wait   │────▶│  Send SMS   │────▶│  Report  │
│  (Trigger)  │     │  (Lambda)    │     │ (until   │     │  (Lambda)   │     │ (Lambda) │
│             │     │              │     │  send-at) │     │             │     │          │
└─────────────┘     └──────────────┘     └──────────┘     └─────────────┘     └──────────┘
```

1. CSV is uploaded to S3 with metadata tag `send-at: 2026-04-08T10:00:00Z`
2. S3 event triggers the Step Functions execution
3. First state: A Lambda reads the S3 object metadata and returns the `send-at` timestamp
4. Wait state: The execution pauses until the specified timestamp
5. Send state: Lambda processes the CSV and sends all messages
6. (Optional) Report state: Lambda generates a delivery summary and sends a notification

**Advantages:**
- Visual workflow — easy to understand and debug in the Step Functions console
- Built-in retry and error handling at each state
- Can add approval steps, conditional logic, or parallel processing
- Execution history provides a full audit trail
- Wait state supports timestamps up to 1 year in the future

**Considerations:**
- Step Functions charges per state transition ($0.025 per 1,000 transitions)
- Each waiting execution consumes a slot (default limit: 1,000,000 concurrent executions per region, so this is rarely an issue)
- More complex initial setup compared to EventBridge Scheduler

---

## Comparison Summary

| Capability | EventBridge Scheduler | DynamoDB + Poller | Step Functions |
|---|---|---|---|
| Complexity | Low | Medium | Medium-High |
| Time zone support | Native | Manual (convert in code) | Manual (use UTC) |
| Cancel/reschedule | Delete/update schedule | Update DynamoDB record | Stop execution |
| Visibility into pending sends | List schedules via API | Query DynamoDB table | View executions in console |
| Part of larger workflow | No (standalone) | No (standalone) | Yes (add any states) |
| Cost | Very low | Low | Low-Medium |
| Best for | Most use cases | Campaign management | Complex workflows |

## Throttling and Rate Limits

AWS End User Messaging enforces per-second sending limits (TPS) based on your origination identity type:

| Origination Type | Typical TPS |
|---|---|
| 10DLC (low-vetting score) | 1–4 TPS |
| 10DLC (high-vetting score) | Up to 75 TPS |
| Toll-free | 3 TPS |
| Short code | 100 TPS |

**For small lists (under 1,000 numbers):** A simple delay between API calls in your Lambda function (e.g., 50–100ms) is sufficient to stay within limits.

**For large lists (1,000+ numbers):** Consider using Amazon SQS as a buffer between the CSV reader and the sender. The reader Lambda pushes each phone number as a message to an SQS queue, and a sender Lambda processes the queue at a controlled concurrency using reserved concurrency settings. This gives you natural backpressure and retry handling.

## Error Handling Recommendations

- Wrap each `SendTextMessage` API call in error handling (try/catch)
- Log failures with the phone number and error message to CloudWatch
- Consider writing failed numbers to a separate CSV in S3 (e.g., `failed/campaign-april-failures.csv`) for easy retry
- Set up a CloudWatch Alarm on Lambda errors to get notified if something goes wrong during a send
- Use Dead Letter Queues (DLQ) on your Lambda function to capture events that fail after all retries

## Opt-Out Compliance

- AWS End User Messaging automatically handles STOP/HELP keyword responses at the carrier level
- You are responsible for maintaining your own opt-out list and filtering your CSV before uploading
- Do not send to numbers that have previously opted out
- Include opt-out instructions in your message content where required by regulation

## Cost Considerations

| Component | Pricing Model |
|---|---|
| SMS messages | Per message segment, varies by destination country |
| Lambda | Per invocation + duration (free tier: 1M requests/month) |
| S3 | Per GB stored + per request (negligible for CSV files) |
| EventBridge Scheduler | Free tier covers 14M invocations/month |
| DynamoDB (if used) | On-demand: per read/write request |
| Step Functions (if used) | $0.025 per 1,000 state transitions |

The dominant cost will be the SMS messages themselves.

---

## Next Steps

1. Decide which scheduling option fits your use case
2. Set up the core components (S3 bucket, Lambda function, IAM role)
3. Test with a small CSV of numbers you control
4. Add your chosen scheduling mechanism
5. Build a simple upload interface if needed (API Gateway + S3 presigned URLs work well for this)

For questions about origination identity setup, 10DLC registration, or sending limits, refer to the [AWS End User Messaging documentation](https://docs.aws.amazon.com/sms-voice/latest/userguide/) or contact your AWS account team.
