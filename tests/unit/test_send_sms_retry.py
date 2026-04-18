"""Unit tests for send_sms retry logic with exponential backoff."""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Add the sender lambda directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lambda", "sms_sender"))


def make_client_error(code, message="Throttled"):
    """Create a botocore ClientError with the given error code."""
    from botocore.exceptions import ClientError
    return ClientError(
        {"Error": {"Code": code, "Message": message}},
        "SendTextMessage",
    )


def make_job(phone="+15559876543", message="Hello"):
    """Create a minimal send job dict matching the current send_sms(job) signature."""
    return {
        "phone_number": phone,
        "message_body": message,
        "origination_identity": "+15551234567",
        "message_type": "TRANSACTIONAL",
        "campaign_name": "unit-test",
        "campaign_id": "unit-test-001",
    }


class TestSendSmsRetry(unittest.TestCase):
    """Test retry behavior in send_sms."""

    def setUp(self):
        """Set required env vars before importing the module."""
        os.environ["MAX_RETRIES"] = "3"
        # Force re-import so MAX_RETRIES is picked up fresh
        if "app" in sys.modules:
            del sys.modules["app"]

    @patch("time.sleep")
    def test_succeeds_on_first_attempt(self, mock_sleep):
        """Normal send — no retries needed."""
        import app
        app.sms = MagicMock()
        app.sms.send_text_message.return_value = {"MessageId": "msg-123"}

        app.send_sms(make_job())

        self.assertEqual(app.sms.send_text_message.call_count, 1)
        mock_sleep.assert_not_called()

    @patch("time.sleep")
    def test_retries_on_throttling_then_succeeds(self, mock_sleep):
        """Throttled twice, succeeds on third attempt."""
        import app
        app.sms = MagicMock()
        app.sms.send_text_message.side_effect = [
            make_client_error("ThrottlingException"),
            make_client_error("ThrottlingException"),
            {"MessageId": "msg-456"},
        ]

        app.send_sms(make_job())

        self.assertEqual(app.sms.send_text_message.call_count, 3)
        # Backoff: 2^1=2s, 2^2=4s
        self.assertEqual(mock_sleep.call_args_list[0][0][0], 2)
        self.assertEqual(mock_sleep.call_args_list[1][0][0], 4)

    @patch("time.sleep")
    def test_fails_after_max_retries_exhausted(self, mock_sleep):
        """Throttled on all 3 attempts — raises on final attempt."""
        import app
        app.sms = MagicMock()
        app.sms.send_text_message.side_effect = [
            make_client_error("ThrottlingException"),
            make_client_error("ThrottlingException"),
            make_client_error("ThrottlingException", "Rate exceeded"),
        ]

        from botocore.exceptions import ClientError
        with self.assertRaises(ClientError) as ctx:
            app.send_sms(make_job())

        self.assertIn("Rate exceeded", str(ctx.exception))
        self.assertEqual(app.sms.send_text_message.call_count, 3)

    @patch("time.sleep")
    def test_retries_on_too_many_requests(self, mock_sleep):
        """TooManyRequestsException also triggers retry."""
        import app
        app.sms = MagicMock()
        app.sms.send_text_message.side_effect = [
            make_client_error("TooManyRequestsException"),
            {"MessageId": "msg-789"},
        ]

        app.send_sms(make_job())

        self.assertEqual(app.sms.send_text_message.call_count, 2)

    @patch("time.sleep")
    def test_no_retry_on_validation_error(self, mock_sleep):
        """Non-throttle errors raise immediately — no retry."""
        import app
        app.sms = MagicMock()
        app.sms.send_text_message.side_effect = [
            make_client_error("ValidationException", "Invalid phone number"),
        ]

        from botocore.exceptions import ClientError
        with self.assertRaises(ClientError):
            app.send_sms(make_job())

        self.assertEqual(app.sms.send_text_message.call_count, 1)
        mock_sleep.assert_not_called()

    @patch("time.sleep")
    def test_handler_reports_batch_item_failure(self, mock_sleep):
        """Handler returns failed message IDs for SQS partial batch failure."""
        import app
        import json
        app.sms = MagicMock()
        app.sms.send_text_message.side_effect = [
            {"MessageId": "msg-ok"},
            make_client_error("ValidationException", "Bad number"),
        ]

        event = {
            "Records": [
                {"messageId": "sqs-1", "body": json.dumps(make_job("+15551111111"))},
                {"messageId": "sqs-2", "body": json.dumps(make_job("+15552222222"))},
            ]
        }

        result = app.handler(event, None)

        # First message succeeds, second fails — only second reported
        self.assertEqual(len(result["batchItemFailures"]), 1)
        self.assertEqual(result["batchItemFailures"][0]["itemIdentifier"], "sqs-2")


if __name__ == "__main__":
    unittest.main()
