# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security

- **KMS encryption for SQS queues** — both the send queue and DLQ are now encrypted at rest with a dedicated KMS key (`StackKmsKey`). Lambda roles updated with `kms:Decrypt` and `kms:GenerateDataKey` permissions.
- **KMS encryption for SNS topic** — the DLQ alarm SNS topic is now encrypted with the same KMS key.
- **KMS encryption for DynamoDB** — the SMS template table now uses SSE with a customer-managed KMS key instead of the default AWS-owned key.
- **DynamoDB point-in-time recovery** — enabled PITR on the template table for backup and restore capability.
- **S3 access logging** — added a dedicated access logs bucket with a 90-day lifecycle policy. The main bulk SMS bucket now logs all access to this bucket.

### Fixed

- **Unit tests updated** — rewrote `test_send_sms_retry.py` to match the current `send_sms(job)` function signature. Added a new `test_handler_reports_batch_item_failure` test for SQS partial batch failure reporting. All 6 tests passing.

### Added

- **SQS fan-out architecture** — replaced sequential send loop with a Dispatcher/Sender pattern. The Dispatcher Lambda validates the CSV and writes individual send jobs to SQS; the Sender Lambda consumes from the queue with concurrency-controlled throughput. Eliminates `time.sleep()` idle compute costs and scales to millions of messages.
- **Dead-letter queue (DLQ)** — failed sends that exhaust SQS retries (3 attempts) land in a DLQ with 14-day retention. Optional CloudWatch alarm + SNS email notification when messages hit the DLQ.
- **CSV pre-flight validation** — full CSV validation before any messages are queued: checks for required `phone_number` header, validates at least one message source exists, and verifies template variables match CSV columns. Fails the entire job upfront with a clear error report.
- **Tiered template resolution** — messages are resolved in priority order: (1) per-row `message` column in CSV, (2) inline `message_template` in the request payload with `{{variable}}` substitution, (3) `template_id` referencing a stored template in DynamoDB. If no message source is provided, the job fails immediately.
- **DynamoDB template table** — optional `{StackPrefix}-templates` table for storing reusable SMS templates with `template_id` as the partition key. Templates are validated against CSV columns at dispatch time.
- **Campaign context** — every send now carries `campaign_name` and a unique `campaign_id` (name + 8-char UUID suffix) in the `Context` parameter, flowing through to CloudWatch and event destinations for analytics and reporting. `campaign_name` is required.
- **SQS partial batch failure reporting** — the Sender Lambda uses `ReportBatchItemFailures` so only failed messages return to the queue; successful sends in the same batch are not reprocessed.

### Removed

- **`DEFAULT_MESSAGE` environment variable** — removed the silent fallback to a default message. If no message source is configured, the job now fails explicitly to prevent accidental sends with wrong content.
- **`SEND_DELAY_MS` environment variable** — throttling is now controlled by Sender Lambda reserved concurrency (`SenderConcurrency` parameter) instead of `time.sleep()`.

### Changed

- **SAM template rewritten** — now deploys Dispatcher Lambda, Sender Lambda, SQS send queue, DLQ, DynamoDB template table, CloudWatch alarm, SNS topic, and updated IAM roles. Replaced single-Lambda architecture.
- **Architecture diagram** — added proper AWS architecture diagram (`documentation/architecture/bulk-sms-and-scheduling-system-architecture.png`), replacing ASCII art in README and setup guide.
- **README rewritten** — updated for Dispatcher/Sender architecture, tiered templates, campaign context, throughput control, DLQ handling, and new deploy parameters.
- **Setup guide rewritten** — updated `documentation/user-guides/bulk-sms-and-scheduling-setup-guide.md` for the new architecture with manual setup steps, updated IAM permissions, and new environment variables.
- **EventBridge Scheduler payload** — now requires `campaign_name` in the invocation payload for scheduled sends.
- **Sender Lambda throttle handling** — retry with exponential backoff for throttled `SendTextMessage` calls within a single invocation, with SQS-level retry for persistent failures.

### Changed

- **README rewritten** — now documents SAM deployment, dual-mode sending (immediate via S3 trigger + scheduled via EventBridge Scheduler), and updated architecture diagram
- **Setup guide updated** — added BOM encoding note and template variable placeholder behavior documentation

### Security

- **PII scrubbed from test files** — all test CSVs use placeholder phone numbers, no real numbers or account IDs in committed files

## [0.1.0] - 2026-04-09

### Added

- **Lambda function** for CSV-based bulk SMS sending via AWS End User Messaging
- **Three CSV format options**: phone-only, phone+message, and template variables with `{{placeholder}}` support
- **S3 file lifecycle**: automatic move from `incoming/` to `processed/` after send
- **S3 log files**: per-row send results written to `logs/` prefix as plain text
- **Configurable send throttling** via `SEND_DELAY_MS` environment variable
- **Configuration set support** for delivery event tracking
- **Setup guide** with three scheduling options: EventBridge Scheduler, DynamoDB polling, and Step Functions
- **E.164 phone number validation** — invalid phone numbers are rejected before calling the SMS API
- **S3 event parameter validation** — malformed S3 event records are caught and logged instead of crashing the function
- **S3 GetObject error handling** — failed CSV downloads return a structured error instead of an unhandled exception

### Security

- **IAM wildcard removed** — `sms-voice:SendTextMessage` resource scoped to specific origination identity ARN with condition key
- **S3 bucket security hardening** — Block Public Access, encryption at rest, HTTPS enforcement, versioning, and access logging guidance
- **Lambda environment variable encryption** — KMS encryption guidance for sensitive configuration
- **Data classification table** — PII handling procedures for phone numbers and message content
- **Threat model** — STRIDE-based threat analysis covering all trust boundaries
- **Risk assessment** — consolidated risk/likelihood/impact/mitigation table
- **Security guidelines per service** — guidance for S3, Lambda, End User Messaging, EventBridge Scheduler, DynamoDB, Step Functions
- **Actionable IAM policy** — complete IAM policy JSON and AWS CLI commands for role creation
