# ADR-001: Security Scan Remediation — Accepted Risks

**Status:** Accepted
**Date:** 2026-04-17
**Deciders:** Tyler Holmes

## Context

A Holmes Content Security Review scan of `template.yaml` returned 22 findings across SQS, SNS, DynamoDB, S3, and IAM resources. We remediated 18 findings by adding KMS encryption, S3 access logging, and DynamoDB point-in-time recovery. The remaining findings were evaluated and accepted as low-risk or inapplicable to this project.

A follow-up scan confirmed 13 remaining findings (the original 4 skipped items plus 9 new findings on the AccessLogsBucket we added).

## Decision

The following scanner findings are accepted and will not be remediated.

### 1. IAM Inline Policy on SchedulerRole (`IAM_NO_INLINE_POLICY_CHECK`)

**Scanner:** cfn-guard
**Risk accepted:** The SchedulerRole uses an inline policy scoped to a single action (`lambda:InvokeFunction`) on a single resource (the Dispatcher Lambda ARN). Converting to a managed policy adds operational complexity (separate resource lifecycle, naming, potential orphaning) with no meaningful security improvement. The policy is already least-privilege.

### 2. S3 ObjectLock on BulkSmsBucket (`S3_BUCKET_DEFAULT_LOCK_ENABLED`)

**Scanner:** cfn-guard, Checkov
**Risk accepted:** ObjectLock enforces write-once-read-many (WORM) semantics. The Dispatcher Lambda moves CSVs from `incoming/` to `processed/` and writes log files — ObjectLock would break this core workflow. The bucket is already protected by KMS encryption, versioning, public access block, and TLS-only policy.

### 3. S3 ObjectLock on AccessLogsBucket (`S3_BUCKET_DEFAULT_LOCK_ENABLED`)

**Scanner:** cfn-guard
**Risk accepted:** Access logs are ephemeral with a 90-day lifecycle expiration. ObjectLock would prevent lifecycle cleanup and cause unbounded storage growth. The bucket has encryption, public access block, and TLS-only policy.

### 4. S3 Public ACL Check (`S3_BUCKET_NO_PUBLIC_RW_ACL`)

**Scanner:** cfn-guard
**Risk accepted:** Both buckets have `PublicAccessBlockConfiguration` with all four settings enabled (`BlockPublicAcls`, `BlockPublicPolicy`, `IgnorePublicAcls`, `RestrictPublicBuckets`). The scanner flags the missing `AccessControl` property, but the block configuration is a stronger control that overrides any ACL. This is a false positive.

### 5. S3 SSL-Only Transport (`S3_BUCKET_SSL_REQUESTS_ONLY`)

**Scanner:** cfn-guard
**Risk accepted:** Both `BulkSmsBucketPolicy` and `AccessLogsBucketPolicy` include a `DenyInsecureTransport` statement that denies all `s3:*` actions when `aws:SecureTransport` is false. The scanner checks at the template level rather than evaluating the bucket policy content, resulting in a false positive.

### 6. Access Logging on AccessLogsBucket (`CKV_AWS_18`, `S3_BUCKET_LOGGING_ENABLED`)

**Scanner:** Checkov, cfn-guard
**Risk accepted:** Enabling access logging on the logging bucket itself creates a recursive logging loop. AWS documentation explicitly advises against this. The AccessLogsBucket is a destination-only bucket with no direct user access.

### 7. Versioning on AccessLogsBucket (`CKV_AWS_21`, `S3_BUCKET_VERSIONING_ENABLED`)

**Scanner:** Checkov, cfn-guard
**Risk accepted:** Access logs are ephemeral diagnostic data with a 90-day lifecycle policy. Versioning would retain deleted log versions indefinitely, increasing storage costs with no operational benefit. The logs are not a source of truth that requires version history.

## Consequences

### Positive
- Clear documentation of why each finding was accepted
- Faster future scan reviews — reviewers can reference this ADR
- Reduced noise in scan reports by documenting known acceptable findings

### Negative
- 13 findings will persist in future scans until scanner rules are updated or exemptions are configured

### Neutral
- If the project's risk profile changes (e.g., handling regulated data), these decisions should be revisited
