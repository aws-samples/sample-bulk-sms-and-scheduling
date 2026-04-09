# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- **E.164 phone number validation** added to Lambda — invalid phone numbers are now rejected before calling the SMS API
- **S3 event parameter validation** — malformed S3 event records are caught and logged instead of crashing the function
- **S3 GetObject error handling** — failed CSV downloads now return a structured error instead of an unhandled exception

### Security

- **IAM wildcard removed** — `sms-voice:SendTextMessage` resource scoped to specific origination identity ARN with condition key in both README and setup guide
- **S3 bucket security hardening** — added Block Public Access, encryption at rest, HTTPS enforcement, versioning, and access logging guidance with CLI commands
- **Lambda environment variable encryption** — added KMS encryption guidance for sensitive configuration
- **Data classification table** — documented PII handling procedures for phone numbers and message content
- **Threat model** — added STRIDE-based threat analysis covering all trust boundaries
- **Risk assessment** — added consolidated risk/likelihood/impact/mitigation table
- **Security guidelines per service** — added security guidance for all 6 AWS services (S3, Lambda, End User Messaging, EventBridge Scheduler, DynamoDB, Step Functions)
- **Actionable IAM policy** — added complete IAM policy JSON and AWS CLI commands for role creation

### Changed

- **AWS service naming** — corrected first mentions to use full service names (Amazon EventBridge Scheduler, Amazon API Gateway, Amazon Simple Queue Service)
- **Superlative language** — replaced "Best for" with "Best suited for" and "Recommended for" per AWS content guidelines

## [0.1.0] - 2026-04-09

### Added

- **Lambda function** for CSV-based bulk SMS sending via AWS End User Messaging
- **Three CSV format options**: phone-only, phone+message, and template variables with `{{placeholder}}` support
- **S3 file lifecycle**: automatic move from `incoming/` to `processed/` after send
- **S3 log files**: per-row send results written to `logs/` prefix as plain text
- **Configurable send throttling** via `SEND_DELAY_MS` environment variable
- **Configuration set support** for delivery event tracking
- **Setup guide** with three scheduling options: EventBridge Scheduler, DynamoDB polling, and Step Functions
