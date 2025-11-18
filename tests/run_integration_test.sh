#!/bin/bash
set -e

echo "========================================="
echo "SMTPBench Integration Test"
echo "========================================="
echo ""

# Clean up previous test artifacts
echo "Cleaning up previous test artifacts..."
rm -rf test-mail logs
mkdir -p test-mail logs

# Start services
echo "Starting mail server and SMTPBench..."
docker-compose -f docker-compose.test.yml up --build -d mail-server

# Wait for mail server to be ready
echo "Waiting for mail server to be ready..."
sleep 5

# Run SMTPBench
echo "Running SMTPBench load test..."
docker-compose -f docker-compose.test.yml up --build smtpbench

# Wait a bit for messages to be processed
echo "Waiting for messages to be processed..."
sleep 5

# Run validation
echo "Running validation..."
docker-compose -f docker-compose.test.yml up --build validator
VALIDATOR_EXIT_CODE=$?

# If validator container failed, get the actual exit code
if [ $VALIDATOR_EXIT_CODE -ne 0 ]; then
    VALIDATOR_EXIT_CODE=$(docker inspect test-validator --format='{{.State.ExitCode}}' 2>/dev/null || echo 1)
fi

# Show logs summary
echo ""
echo "========================================="
echo "Test Results"
echo "========================================="
if [ $VALIDATOR_EXIT_CODE -eq 0 ]; then
    echo "✅ Integration test PASSED"
else
    echo "❌ Integration test FAILED"
fi

# Show SMTPBench logs
echo ""
echo "SMTPBench logs:"
docker-compose -f docker-compose.test.yml logs smtpbench | tail -n 20

# Cleanup
echo ""
echo "Cleaning up containers..."
docker-compose -f docker-compose.test.yml down

# Show final results
echo ""
echo "========================================="
echo "Summary"
echo "========================================="
echo "Check logs/ directory for detailed SMTPBench logs"
echo "Check test-mail/ directory for received emails"
echo ""

exit $VALIDATOR_EXIT_CODE
