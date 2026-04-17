"""
CSV Bulk SMS Dispatcher Lambda

Triggered by S3 ObjectCreated events on the incoming/ prefix or direct invocation.
Validates the CSV upfront, resolves the message template, then writes individual
send jobs to SQS for the Sender Lambda to process.

Template Resolution Priority:
    1. Per-row 'message' column in the CSV (fully resolved, no substitution)
    2. Inline 'message_template' in the request payload (with {{variable}} substitution)
    3. 'template_id' referencing a stored template in DynamoDB
    If none are provided, the job fails before any messages are queued.

Required in request payload (direct invocation) or derived from S3 event:
    campaign_name - Human-readable campaign identifier (REQUIRED)

Environment Variables:
    ORIGINATION_IDENTITY - The origination phone number or ARN
    MESSAGE_TYPE         - TRANSACTIONAL or PROMOTIONAL (default: TRANSACTIONAL)
    CONFIGURATION_SET    - The configuration set name for event tracking
    SQS_QUEUE_URL        - URL of the SQS queue for send jobs
    TEMPLATE_TABLE_NAME  - DynamoDB table name for stored templates
"""

import csv
import io
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

E164_PATTERN = re.compile(r"^\+[1-9]\d{1,14}$")
PLACEHOLDER_PATTERN = re.compile(r"\{\{(\w+)\}\}")

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")
sqs = boto3.client("sqs")
dynamodb = boto3.resource("dynamodb")

ORIGINATION_IDENTITY = os.environ.get("ORIGINATION_IDENTITY", "")
MESSAGE_TYPE = os.environ.get("MESSAGE_TYPE", "TRANSACTIONAL")
CONFIGURATION_SET = os.environ.get("CONFIGURATION_SET", "")
SQS_QUEUE_URL = os.environ["SQS_QUEUE_URL"]
TEMPLATE_TABLE_NAME = os.environ.get("TEMPLATE_TABLE_NAME", "")


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

def handler(event, context):
    """Main Lambda handler — supports S3 event triggers and direct invocation.

    S3 trigger format:  {"Records": [{"s3": {"bucket": {"name": "..."}, "object": {"key": "..."}}}]}
    Direct invocation:  {"bucket": "my-bucket", "key": "scheduled/my-file.csv", "campaign_name": "..."}
    """
    logger.info("Event received: %s", json.dumps(event, default=str))

    # Direct invocation (e.g. from EventBridge Scheduler)
    if "bucket" in event and "key" in event:
        bucket = event["bucket"]
        key = event["key"]
        campaign_name = event.get("campaign_name")
        message_template = event.get("message_template")
        template_id = event.get("template_id")
        return dispatch(bucket, key, campaign_name, message_template, template_id)

    # S3 event trigger — campaign_name derived from filename
    for record in event.get("Records", []):
        try:
            bucket = record["s3"]["bucket"]["name"]
            key = record["s3"]["object"]["key"]
        except (KeyError, TypeError) as e:
            logger.error("Malformed S3 event record, skipping: %s", e)
            continue

        if not key.startswith("incoming/"):
            logger.warning("Skipping file not in incoming/ prefix: %s", key)
            continue

        # For S3 triggers, derive campaign_name from filename
        filename = os.path.basename(key).rsplit(".", 1)[0]
        return dispatch(bucket, key, campaign_name=filename)

    return {"statusCode": 200, "body": "No files to process"}


# ---------------------------------------------------------------------------
# Core dispatch logic
# ---------------------------------------------------------------------------

def dispatch(bucket, key, campaign_name=None, message_template=None, template_id=None):
    """Validate CSV, resolve templates, and write send jobs to SQS."""

    # --- Validate campaign_name ---
    if not campaign_name:
        raise ValueError(
            "'campaign_name' is required. Provide a name to identify this send campaign."
        )

    campaign_id = f"{campaign_name}-{uuid.uuid4().hex[:8]}"
    logger.info("Campaign: %s (id: %s)", campaign_name, campaign_id)

    # --- Read CSV from S3 ---
    try:
        response = s3.get_object(Bucket=bucket, Key=key)
    except ClientError as e:
        logger.error("Failed to read s3://%s/%s: %s", bucket, key, e)
        raise

    body = response["Body"].read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(body))
    fieldnames = [f.strip().lower() for f in (reader.fieldnames or [])]

    # --- Pre-flight CSV validation ---
    errors = validate_csv(fieldnames, message_template, template_id)
    if errors:
        error_msg = "CSV validation failed:\n" + "\n".join(errors)
        logger.error(error_msg)
        write_error_log(bucket, key, campaign_id, errors)
        raise ValueError(error_msg)

    # --- Resolve stored template if needed ---
    stored_template_body = None
    if template_id:
        stored_template_body = fetch_template(template_id)

    has_message_col = "message" in fieldnames
    reserved_cols = {"phone_number", "message"}
    variable_cols = [f for f in fieldnames if f not in reserved_cols]

    # --- Process rows and write to SQS ---
    total = 0
    queued = 0
    skipped = 0
    row_errors = []

    for row in reader:
        total += 1
        phone = row.get("phone_number", "").strip()

        # Validate phone number
        if not phone:
            skipped += 1
            row_errors.append(f"Row {total}: empty phone number")
            continue
        if not E164_PATTERN.match(phone):
            skipped += 1
            row_errors.append(f"Row {total}: invalid E.164 format: {phone}")
            continue

        # Resolve message using priority order
        message = resolve_message(row, has_message_col, message_template,
                                  stored_template_body, variable_cols)
        if not message:
            skipped += 1
            row_errors.append(f"Row {total}: empty message for {phone}")
            continue

        # Build SQS message
        sqs_body = {
            "phone_number": phone,
            "message_body": message,
            "campaign_name": campaign_name,
            "campaign_id": campaign_id,
            "origination_identity": ORIGINATION_IDENTITY,
            "message_type": MESSAGE_TYPE,
            "configuration_set": CONFIGURATION_SET,
        }

        sqs.send_message(QueueUrl=SQS_QUEUE_URL, MessageBody=json.dumps(sqs_body))
        queued += 1

    logger.info(
        "Dispatch complete for %s — Total: %d, Queued: %d, Skipped: %d",
        campaign_id, total, queued, skipped,
    )
    if row_errors:
        logger.warning("Row errors:\n%s", "\n".join(row_errors[:50]))

    # Write dispatch log to S3
    write_dispatch_log(bucket, key, campaign_id, campaign_name, total, queued, skipped, row_errors)

    # Move file to processed/
    move_to_processed(bucket, key)

    return {
        "statusCode": 200,
        "campaign_id": campaign_id,
        "total_rows": total,
        "queued": queued,
        "skipped": skipped,
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_csv(fieldnames, message_template=None, template_id=None):
    """Pre-flight validation — returns a list of error strings (empty = valid)."""
    errors = []

    if not fieldnames:
        errors.append("CSV has no headers.")
        return errors

    if "phone_number" not in fieldnames:
        errors.append("CSV is missing required 'phone_number' column.")

    has_message_col = "message" in fieldnames

    # At least one message source must exist
    if not has_message_col and not message_template and not template_id:
        errors.append(
            "No message source provided. Include a 'message' column in your CSV, "
            "a 'message_template' in the request, or a 'template_id' referencing a stored template."
        )

    # If using a template, validate that CSV has the required variable columns
    template_body = None
    if message_template:
        template_body = message_template
    elif template_id:
        try:
            template_body = fetch_template(template_id)
        except Exception as e:
            errors.append(f"Failed to fetch template '{template_id}': {e}")
            return errors

    if template_body and not has_message_col:
        required_vars = set(PLACEHOLDER_PATTERN.findall(template_body))
        available_cols = set(fieldnames) - {"phone_number", "message"}
        missing = required_vars - available_cols
        if missing:
            errors.append(
                f"Template requires columns {sorted(missing)} but CSV only has {sorted(available_cols)}."
            )

    return errors


# ---------------------------------------------------------------------------
# Template resolution
# ---------------------------------------------------------------------------

def resolve_message(row, has_message_col, message_template, stored_template_body, variable_cols):
    """Resolve the message for a single row using the priority order."""

    # Priority 1: per-row message column
    if has_message_col:
        msg = row.get("message", "").strip()
        if msg:
            return msg

    # Priority 2: inline template with variable substitution
    if message_template:
        return substitute(message_template, row, variable_cols)

    # Priority 3: stored DynamoDB template
    if stored_template_body:
        return substitute(stored_template_body, row, variable_cols)

    return None


def substitute(template, row, variable_cols):
    """Replace {{placeholder}} tokens with values from the CSV row."""
    message = template
    for col in variable_cols:
        value = row.get(col, "").strip()
        message = message.replace("{{" + col + "}}", value)
    return message


def fetch_template(template_id):
    """Fetch a message template from DynamoDB by template_id."""
    if not TEMPLATE_TABLE_NAME:
        raise ValueError("TEMPLATE_TABLE_NAME not configured — cannot use template_id.")

    table = dynamodb.Table(TEMPLATE_TABLE_NAME)
    resp = table.get_item(Key={"template_id": template_id})
    item = resp.get("Item")
    if not item:
        raise ValueError(f"Template '{template_id}' not found in {TEMPLATE_TABLE_NAME}.")
    return item["template_body"]


# ---------------------------------------------------------------------------
# S3 helpers
# ---------------------------------------------------------------------------

def write_dispatch_log(bucket, key, campaign_id, campaign_name, total, queued, skipped, row_errors):
    """Write a dispatch summary log to S3."""
    filename = os.path.basename(key).replace(".csv", "")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    log_key = f"logs/{filename}-{campaign_id}-dispatch-{timestamp}.txt"

    lines = [
        "CSV Bulk SMS Dispatch Log",
        f"Source file:    s3://{bucket}/{key}",
        f"Campaign name:  {campaign_name}",
        f"Campaign ID:    {campaign_id}",
        f"Timestamp:      {datetime.now(timezone.utc).isoformat()}",
        "",
        f"Total rows: {total}  |  Queued: {queued}  |  Skipped: {skipped}",
    ]
    if row_errors:
        lines.append("")
        lines.append("--- Skipped Rows ---")
        lines.extend(row_errors[:100])

    try:
        s3.put_object(Bucket=bucket, Key=log_key, Body="\n".join(lines).encode("utf-8"), ContentType="text/plain")
        logger.info("Dispatch log written to s3://%s/%s", bucket, log_key)
    except ClientError as e:
        logger.error("Failed to write dispatch log: %s", e)


def write_error_log(bucket, key, campaign_id, errors):
    """Write a validation error log to S3."""
    filename = os.path.basename(key).replace(".csv", "")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    log_key = f"logs/{filename}-{campaign_id}-validation-error-{timestamp}.txt"

    lines = [
        "CSV Validation Error",
        f"Source file: s3://{bucket}/{key}",
        f"Timestamp:   {datetime.now(timezone.utc).isoformat()}",
        "",
        "--- Errors ---",
    ]
    lines.extend(errors)

    try:
        s3.put_object(Bucket=bucket, Key=log_key, Body="\n".join(lines).encode("utf-8"), ContentType="text/plain")
    except ClientError as e:
        logger.error("Failed to write error log: %s", e)


def move_to_processed(bucket, key):
    """Move the CSV from incoming/ or scheduled/ to processed/."""
    if key.startswith("incoming/"):
        new_key = key.replace("incoming/", "processed/", 1)
    elif key.startswith("scheduled/"):
        new_key = key.replace("scheduled/", "processed/", 1)
    else:
        new_key = "processed/" + os.path.basename(key)
    try:
        s3.copy_object(Bucket=bucket, CopySource={"Bucket": bucket, "Key": key}, Key=new_key)
        s3.delete_object(Bucket=bucket, Key=key)
        logger.info("Moved %s → %s", key, new_key)
    except ClientError as e:
        logger.error("Failed to move file: %s", e)
