# Bulk SMS Sender Test Suite

Upload each CSV to `s3://BUCKET/incoming/` and verify the expected behavior.

## Test Matrix

| # | File | Format | Tests |
|---|---|---|---|
| 1 | `test-01-phone-only.csv` | A (phone only) | Uses DEFAULT_MESSAGE env var, single recipient |
| 2 | `test-02-multi-phone-only.csv` | A (phone only) | Multiple recipients, same default message |
| 3 | `test-03-unique-messages.csv` | B (phone+message) | Each row has its own message |
| 4 | `test-04-template-vars.csv` | C (template) | {{name}} and {{code}} placeholders |
| 5 | `test-05-mixed-valid-invalid.csv` | Edge case | Mix of valid E.164, invalid numbers, empty rows |
| 6 | `test-06-quoted-commas.csv` | B (phone+message) | Message body contains commas (quoted field) |
| 7 | `test-07-empty-file.csv` | Edge case | Headers only, no data rows |
| 8 | `test-08-bom.csv` | Edge case | UTF-8 BOM prefix (tests the utf-8-sig fix) |

## Expected DEFAULT_MESSAGE

Set this on the Lambda before running tests 1, 2, and 4:

```
Hi {{name}}, your verification code is {{code}}. This expires in 10 minutes.
```

For tests 1 and 2 (no template vars in CSV), the `{{name}}` and `{{code}}` placeholders will remain as literal text — that's expected.

## How to Run

```bash
BUCKET="YOUR-BUCKET-NAME"
REGION="us-west-2"
# Upload one at a time
aws s3 cp tests/test-01-phone-only.csv s3://$BUCKET/incoming/ --region $REGION

# Check logs
aws logs tail /aws/lambda/BulkSmsSender --since 2m --region $REGION

# Check S3 log file
aws s3 ls s3://$BUCKET/logs/ --region $REGION
```
