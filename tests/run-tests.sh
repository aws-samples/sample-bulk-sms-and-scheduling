#!/bin/bash
# Run bulk SMS sender test suite one file at a time
# Usage: ./run-tests.sh [test-number]
#   ./run-tests.sh        — runs all tests sequentially
#   ./run-tests.sh 3      — runs only test 03

BUCKET="YOUR-BUCKET-NAME"
REGION="us-west-2"
TESTS_DIR="$(dirname "$0")"

run_test() {
    local file="$1"
    local name=$(basename "$file")
    echo ""
    echo "=========================================="
    echo "  UPLOADING: $name"
    echo "=========================================="
    aws s3 cp "$file" "s3://$BUCKET/incoming/$name" --region "$REGION"
    echo "Waiting 15 seconds for Lambda to process..."
    sleep 15
    echo ""
    echo "--- CloudWatch Logs ---"
    aws logs tail "/aws/lambda/BulkSmsSender" --since 1m --region "$REGION" | grep -E "(Summary|Errors|Sent to|Failed to|SKIP|empty)"
    echo ""
    echo "--- S3 Log File ---"
    LATEST_LOG=$(aws s3 ls "s3://$BUCKET/logs/" --region "$REGION" | sort | tail -1 | awk '{print $4}')
    if [ -n "$LATEST_LOG" ]; then
        aws s3 cp "s3://$BUCKET/logs/$LATEST_LOG" - --region "$REGION"
    fi
    echo ""
    echo "Press Enter to continue to next test..."
    read
}

if [ -n "$1" ]; then
    FILE=$(printf "%s/test-%02d-*.csv" "$TESTS_DIR" "$1")
    FILE=$(ls $FILE 2>/dev/null | head -1)
    if [ -z "$FILE" ]; then
        echo "Test $1 not found"
        exit 1
    fi
    run_test "$FILE"
else
    for f in "$TESTS_DIR"/test-*.csv; do
        run_test "$f"
    done
fi

echo "All tests complete."
