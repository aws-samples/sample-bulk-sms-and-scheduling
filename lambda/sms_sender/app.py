"""
SMS Sender Lambda

Consumes messages from SQS and sends SMS via AWS End User Messaging.
Each SQS message contains a single fully-resolved send job — this Lambda
is intentionally simple: parse, send, done.

Throttling is controlled by Lambda reserved concurrency, not by sleep().
Retry is handled by SQS visibility timeout + redrive policy (DLQ).

Environment Variables:
    MAX_RETRIES - Max retry attempts for transient API errors within a single invocation (default: 2)
"""

import json
import logging
import os
import time

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

sms = boto3.client("pinpoint-sms-voice-v2")

MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "2"))


def handler(event, context):
    """Process a batch of SQS messages, each containing one SMS send job."""
    batch_failures = []

    for record in event.get("Records", []):
        message_id = record["messageId"]
        try:
            body = json.loads(record["body"])
            send_sms(body)
        except Exception as e:
            logger.error("Failed to process message %s: %s", message_id, e)
            # Report as batch item failure so only this message returns to the queue
            batch_failures.append({"itemIdentifier": message_id})

    # Partial batch failure reporting — successfully sent messages are deleted,
    # failed messages return to the queue for retry (and eventually DLQ).
    return {"batchItemFailures": batch_failures}


def send_sms(job):
    """Send a single SMS with retry for transient errors."""
    phone = job["phone_number"]
    message = job["message_body"]
    campaign_name = job.get("campaign_name", "")
    campaign_id = job.get("campaign_id", "")

    params = {
        "DestinationPhoneNumber": phone,
        "OriginationIdentity": job["origination_identity"],
        "MessageBody": message,
        "MessageType": job.get("message_type", "TRANSACTIONAL"),
        "Context": {
            "campaign_name": campaign_name,
            "campaign_id": campaign_id,
        },
    }

    config_set = job.get("configuration_set")
    if config_set:
        params["ConfigurationSetName"] = config_set

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = sms.send_text_message(**params)
            msg_id = resp.get("MessageId", "unknown")
            logger.info(
                "Sent to %s — MessageId: %s | campaign: %s",
                phone, msg_id, campaign_id,
            )
            return
        except ClientError as e:
            error_code = e.response["Error"]["Code"]

            # Retry on throttling only
            if error_code in ("ThrottlingException", "TooManyRequestsException") and attempt < MAX_RETRIES:
                wait = 2 ** attempt
                logger.warning(
                    "Throttled sending to %s (attempt %d/%d), retrying in %ds",
                    phone, attempt, MAX_RETRIES, wait,
                )
                time.sleep(wait)
                continue

            # Non-retryable or final attempt — raise to trigger SQS retry
            logger.error("Failed to send to %s: %s", phone, e.response["Error"]["Message"])
            raise
