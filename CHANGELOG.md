# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **SAM template** (`template.yaml`) — one-command deployment of S3 bucket, Lambda function, IAM roles, S3 event trigger, and EventBridge Scheduler role
- **SAM config** (`samconfig.toml`) — repeatable deploy defaults for `sam deploy`
- **EventBridge Scheduler support** — Lambda handler now accepts direct invocation with `{"bucket", "key"}` payload in addition to S3 event triggers, enabling scheduled sends
- **EventBridge Scheduler IAM role** — deployed with the stack, scoped to invoke only the bulk SMS Lambda
- **Throttle retry with exponential backoff** — throttled `SendTextMessage` calls are retried up to `MAX_RETRIES` times (default 3) with exponential backoff (2s, 4s, 8s) before marking the row as failed
- **Test suite** — 8 CSV test files covering all formats (phone-only, unique messages, template variables) and edge cases (invalid numbers, empty files, quoted commas, UTF-8 BOM)
- **Test runner script** (`tests/run-tests.sh`) — sequential test execution with log checking
- **Multi-stack support** — `StackPrefix` parameter allows deploying multiple isolated stacks (e.g. marketing vs transactional) in the same account without name collisions

### Fixed

- **UTF-8 BOM handling** — CSV parsing now uses `utf-8-sig` codec so files saved from Windows tools (Excel, Notepad) with a BOM prefix are parsed correctly
- **`move_to_processed` for scheduled files** — files in `scheduled/` prefix are now correctly moved to `processed/` after sending (previously only `incoming/` was handled)

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
