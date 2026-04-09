# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-04-09

### Added

- **Lambda function** for CSV-based bulk SMS sending via AWS End User Messaging
- **Three CSV format options**: phone-only, phone+message, and template variables with `{{placeholder}}` support
- **S3 file lifecycle**: automatic move from `incoming/` to `processed/` after send
- **S3 log files**: per-row send results written to `logs/` prefix as plain text
- **Configurable send throttling** via `SEND_DELAY_MS` environment variable
- **Configuration set support** for delivery event tracking
- **Setup guide** with three scheduling options: EventBridge Scheduler, DynamoDB polling, and Step Functions
