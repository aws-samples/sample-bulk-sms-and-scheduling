"""Unit tests for send_sms retry logic with exponential backoff."""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Add the lambda directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lambda", "bulk_sms_sender"))


def make_client_error(code, message="Throttled"):
    """Create a botocore ClientError with the given error code."""
    from botocore.exceptions import ClientError
    return ClientError(
        {"Error": {"Code": code, "Message": message}},
        "SendTextMessage",
    )


class TestSendSmsRetry(unittest.TestCase):
    """Test retry behavior in send_sms."""

    def setUp(self):
        """Set required env vars and import the module fresh."""
        os.environ["ORIGINATION_IDENTITY"] = "+15551234567"
        os.environ["DEFAULT_MESSAGE"] = "test"
        os.environ["MESSAGE_TYPE"] = "TRANSACTIONAL"
        os.environ["CONFIGURATION_SET"] = ""
        os.environ["SEND_DELAY_MS"] = "0"
        os.environ["MAX_RETRIES"] = "3"

    @patch("time.sleep")
    def test_succeeds_on_first_attempt(self, mock_sleep):
        """Normal send — no retries needed."""
        import app
        app.sms = MagicMock()
        app.sms.send_text_message.return_value = {"MessageId": "msg-123"}

        results = {"total": 1, "sent": 0, "failed": 0, "errors": [], "log_lines": []}
        success = app.send_sms("+15559876543", "Hello", results)

        self.assertTrue(success)
        self.assertEqual(results["sent"], 1)
        self.assertEqual(results["failed"], 0)
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

        results = {"total": 1, "sent": 0, "failed": 0, "errors": [], "log_lines": []}
        success = app.send_sms("+15559876543", "Hello", results)

        self.assertTrue(success)
        self.assertEqual(results["sent"], 1)
        self.assertEqual(results["failed"], 0)
        self.assertEqual(app.sms.send_text_message.call_count, 3)
        # Backoff: 2^1=2s, 2^2=4s
        self.assertEqual(mock_sleep.call_args_list[0][0][0], 2)
        self.assertEqual(mock_sleep.call_args_list[1][0][0], 4)

    @patch("time.sleep")
    def test_fails_after_max_retries_exhausted(self, mock_sleep):
        """Throttled on all 3 attempts — gives up."""
        import app
        app.sms = MagicMock()
        app.sms.send_text_message.side_effect = [
            make_client_error("ThrottlingException"),
            make_client_error("ThrottlingException"),
            make_client_error("ThrottlingException", "Rate exceeded"),
        ]

        results = {"total": 1, "sent": 0, "failed": 0, "errors": [], "log_lines": []}
        success = app.send_sms("+15559876543", "Hello", results)

        self.assertFalse(success)
        self.assertEqual(results["sent"], 0)
        self.assertEqual(results["failed"], 1)
        self.assertEqual(app.sms.send_text_message.call_count, 3)
        self.assertIn("Rate exceeded", results["errors"][0])

    @patch("time.sleep")
    def test_retries_on_too_many_requests(self, mock_sleep):
        """TooManyRequestsException also triggers retry."""
        import app
        app.sms = MagicMock()
        app.sms.send_text_message.side_effect = [
            make_client_error("TooManyRequestsException"),
            {"MessageId": "msg-789"},
        ]

        results = {"total": 1, "sent": 0, "failed": 0, "errors": [], "log_lines": []}
        success = app.send_sms("+15559876543", "Hello", results)

        self.assertTrue(success)
        self.assertEqual(results["sent"], 1)
        self.assertEqual(app.sms.send_text_message.call_count, 2)

    @patch("time.sleep")
    def test_no_retry_on_validation_error(self, mock_sleep):
        """Non-throttle errors fail immediately — no retry."""
        import app
        app.sms = MagicMock()
        app.sms.send_text_message.side_effect = [
            make_client_error("ValidationException", "Invalid phone number"),
        ]

        results = {"total": 1, "sent": 0, "failed": 0, "errors": [], "log_lines": []}
        success = app.send_sms("+15559876543", "Hello", results)

        self.assertFalse(success)
        self.assertEqual(results["failed"], 1)
        self.assertEqual(app.sms.send_text_message.call_count, 1)
        mock_sleep.assert_not_called()

    @patch("time.sleep")
    def test_log_lines_show_retry_attempt(self, mock_sleep):
        """Log line shows attempt number on retry success."""
        import app
        app.sms = MagicMock()
        app.sms.send_text_message.side_effect = [
            make_client_error("ThrottlingException"),
            {"MessageId": "msg-retry"},
        ]

        results = {"total": 1, "sent": 0, "failed": 0, "errors": [], "log_lines": []}
        app.send_sms("+15559876543", "Hello", results)

        self.assertIn("SENT", results["log_lines"][0])
        self.assertIn("msg-retry", results["log_lines"][0])


if __name__ == "__main__":
    unittest.main()
