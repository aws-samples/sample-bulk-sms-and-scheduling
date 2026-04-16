"""
CSV Bulk SMS Sender Lambda

Triggered by S3 ObjectCreated events on the incoming/ prefix.
Reads a CSV of phone numbers (and optionally messages), sends SMS
via AWS End User Messaging, then moves the file to processed/.

CSV Format A (same message to all):
    phone_number
    +15551234567

CSV Format B (unique message per recipient):
    phone_number,message
    +15551234567,Your appointment is confirmed.

CSV Format C (template variables — extra columns replace {{placeholders}} in the message):
    phone_number,name,code
    +15551234567,Tyler,482910
    Set DEFAULT_MESSAGE to: "Hi {{name}}, your code is {{code}}."

Environment Variables:
    ORIGINATION_IDENTITY - The origination phone number or ARN
    DEFAULT_MESSAGE      - Default message body when CSV has no message column
    MESSAGE_TYPE         - TRANSACTIONAL or PROMOTIONAL (default: TRANSACTIONAL)
    CONFIGURATION_SET    - The configuration set name for event tracking
    S3_BUCKET            - (optional) Override bucket name, otherwise read from event
"""

import csv
import io
import json
import logging
import os
import re
import time
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

# E.164 phone number format: + followed by 1-15 digits
E164_PATTERN = re.compile(r"^\+[1-9]\d{1,14}$")

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")
sms = boto3.client("pinpoint-sms-voice-v2")

ORIGINATION_IDENTITY = os.environ.get("ORIGINATION_IDENTITY", "")
DEFAULT_MESSAGE = os.environ.get("DEFAULT_MESSAGE", "")
MESSAGE_TYPE = os.environ.get("MESSAGE_TYPE", "TRANSACTIONAL")
CONFIGURATION_SET = os.environ.get("CONFIGURATION_SET", "")
SEND_DELAY_MS = int(os.environ.get("SEND_DELAY_MS", "50"))
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "3"))


def handler(event, context):
    """Main Lambda handler — supports S3 event triggers and direct invocation.

    S3 trigger format:  {"Records": [{"s3": {"bucket": {"name": "..."}, "object": {"key": "..."}}}]}
    Direct invocation:  {"bucket": "my-bucket", "key": "scheduled/my-file.csv"}
    """
    logger.info("Event received: %s", json.dumps(event, default=str))

    # Direct invocation (e.g. from EventBridge Scheduler)
    if "bucket" in event and "key" in event:
        bucket = event["bucket"]
        key = event["key"]
        logger.info("Direct invocation — processing file: s3://%s/%s", bucket, key)
        results = process_csv(bucket, key)
        log_summary(results, bucket, key)
        write_s3_log(results, bucket, key)
        move_to_processed(bucket, key)
        return {"statusCode": 200, "body": "Processing complete"}

    # S3 event trigger
    for record in event.get("Records", []):
        try:
            bucket = record["s3"]["bucket"]["name"]
            key = record["s3"]["object"]["key"]
        except (KeyError, TypeError) as e:
            logger.error("Malformed S3 event record, skipping: %s", e)
            continue

        # Safety check — only process files in incoming/
        if not key.startswith("incoming/"):
            logger.warning("Skipping file not in incoming/ prefix: %s", key)
            continue

        logger.info("Processing file: s3://%s/%s", bucket, key)
        results = process_csv(bucket, key)
        log_summary(results, bucket, key)
        write_s3_log(results, bucket, key)
        move_to_processed(bucket, key)

    return {"statusCode": 200, "body": "Processing complete"}


def process_csv(bucket: str, key: str) -> dict:
    """Download and parse the CSV, send SMS for each row."""
    try:
        response = s3.get_object(Bucket=bucket, Key=key)
    except ClientError as e:
        logger.error("Failed to read s3://%s/%s: %s", bucket, key, e)
        return {"total": 0, "sent": 0, "failed": 0, "errors": [f"S3 GetObject failed: {e}"]}

    body = response["Body"].read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(body))

    # Detect CSV format by checking for a 'message' column
    fieldnames = [f.strip().lower() for f in (reader.fieldnames or [])]
    has_message_col = "message" in fieldnames

    # Extra columns beyond phone_number and message are treated as template variables
    reserved_cols = {"phone_number", "message"}
    variable_cols = [f for f in fieldnames if f not in reserved_cols]

    if not has_message_col and not DEFAULT_MESSAGE:
        logger.error("CSV has no 'message' column and DEFAULT_MESSAGE env var is not set.")
        return {"total": 0, "sent": 0, "failed": 0, "errors": ["No message source configured"]}

    results = {"total": 0, "sent": 0, "failed": 0, "errors": [], "log_lines": []}

    for row in reader:
        results["total"] += 1
        phone = row.get("phone_number", "").strip()
        message = row.get("message", "").strip() if has_message_col else DEFAULT_MESSAGE

        if not phone:
            results["failed"] += 1
            results["errors"].append(f"Row {results['total']}: empty phone number")
            results["log_lines"].append(f"Row {results['total']} | SKIP | (empty) | empty phone number")
            continue

        if not E164_PATTERN.match(phone):
            results["failed"] += 1
            results["errors"].append(f"Row {results['total']}: invalid E.164 format: {phone}")
            results["log_lines"].append(f"Row {results['total']} | SKIP | {phone} | invalid E.164 format")
            continue

        if not message:
            results["failed"] += 1
            results["errors"].append(f"Row {results['total']}: empty message for {phone}")
            results["log_lines"].append(f"Row {results['total']} | SKIP | {phone} | empty message")
            continue

        # Substitute {{variable}} placeholders with values from extra CSV columns
        for col in variable_cols:
            value = row.get(col, "").strip()
            message = message.replace("{{" + col + "}}", value)

        success = send_sms(phone, message, results)
        if success and SEND_DELAY_MS > 0:
            time.sleep(SEND_DELAY_MS / 1000.0)

    return results


def send_sms(phone: str, message: str, results: dict) -> bool:
    """Send a single SMS with retry and exponential backoff for throttling."""
    row_num = results["total"]
    params = {
        "DestinationPhoneNumber": phone,
        "OriginationIdentity": ORIGINATION_IDENTITY,
        "MessageBody": message,
        "MessageType": MESSAGE_TYPE,
    }
    if CONFIGURATION_SET:
        params["ConfigurationSetName"] = CONFIGURATION_SET

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = sms.send_text_message(**params)
            msg_id = resp.get("MessageId", "unknown")
            if attempt > 1:
                logger.info("Sent to %s on attempt %d — MessageId: %s", phone, attempt, msg_id)
            else:
                logger.info("Sent to %s — MessageId: %s", phone, msg_id)
            results["sent"] += 1
            results["log_lines"].append(f"Row {row_num} | SENT | {phone} | MessageId: {msg_id}")
            return True
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            error_msg = e.response["Error"]["Message"]

            # Retry on throttling errors only
            if error_code in ("ThrottlingException", "TooManyRequestsException") and attempt < MAX_RETRIES:
                wait = 2 ** attempt  # 2s, 4s, 8s
                logger.warning("Throttled sending to %s (attempt %d/%d), retrying in %ds", phone, attempt, MAX_RETRIES, wait)
                time.sleep(wait)
                continue

            logger.error("Failed to send to %s: %s", phone, error_msg)
            results["failed"] += 1
            results["errors"].append(f"{phone}: {error_msg}")
            results["log_lines"].append(f"Row {row_num} | FAILED | {phone} | {error_msg}")
            return False

    return False


def write_s3_log(results: dict, bucket: str, key: str):
    """Write a plain-text log file to the logs/ prefix in S3."""
    filename = os.path.basename(key).replace(".csv", "")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    log_key = f"logs/{filename}-{timestamp}.txt"

    lines = [
        f"CSV Bulk SMS Send Log",
        f"Source file: s3://{bucket}/{key}",
        f"Timestamp:   {datetime.now(timezone.utc).isoformat()}",
        f"",
        f"Total: {results['total']}  |  Sent: {results['sent']}  |  Failed: {results['failed']}",
        f"",
        f"--- Per-Row Details ---",
    ]
    lines.extend(results.get("log_lines", []))

    if results["errors"]:
        lines.append("")
        lines.append("--- Errors ---")
        lines.extend(results["errors"][:100])

    body = "\n".join(lines)

    try:
        s3.put_object(Bucket=bucket, Key=log_key, Body=body.encode("utf-8"), ContentType="text/plain")
        logger.info("Log file written to s3://%s/%s", bucket, log_key)
    except ClientError as e:
        logger.error("Failed to write log file: %s", e)


def move_to_processed(bucket: str, key: str):
    """Move the CSV from incoming/ or scheduled/ to processed/ after processing."""
    if key.startswith("incoming/"):
        new_key = key.replace("incoming/", "processed/", 1)
    elif key.startswith("scheduled/"):
        new_key = key.replace("scheduled/", "processed/", 1)
    else:
        new_key = "processed/" + os.path.basename(key)
    try:
        s3.copy_object(
            Bucket=bucket,
            CopySource={"Bucket": bucket, "Key": key},
            Key=new_key,
        )
        s3.delete_object(Bucket=bucket, Key=key)
        logger.info("Moved %s → %s", key, new_key)
    except ClientError as e:
        logger.error("Failed to move file: %s", e)


def log_summary(results: dict, bucket: str, key: str):
    """Log a summary of the send operation."""
    logger.info(
        "Summary for s3://%s/%s — Total: %d, Sent: %d, Failed: %d",
        bucket, key, results["total"], results["sent"], results["failed"],
    )
    if results["errors"]:
        logger.warning("Errors:\n%s", "\n".join(results["errors"][:50]))
