#!/bin/bash

# AWS Lambda Environment Variables Setup Script
# This script reads your .env file and sets Lambda environment variables

set -e  # Exit on error

echo "Setting Lambda Environment Variables"
echo ""

# Configuration
FUNCTION_NAME="exotel-analytics-scheduler"
REGION="ap-south-1"  # Mumbai region

# Check if AWS CLI is installed
if ! command -v aws &> /dev/null; then
    echo "Error: AWS CLI is not installed"
    exit 1
fi

# Check if .env file exists
if [ ! -f .env ]; then
    echo "Error: .env file not found"
    echo "Please create a .env file with your configuration"
    exit 1
fi

# Load environment variables from .env file (properly handling spaces and special chars)
set -a  # Automatically export all variables
while IFS='=' read -r key value; do
    # Skip comments and empty lines
    [[ $key =~ ^#.*$ ]] && continue
    [[ -z $key ]] && continue
    # Remove leading/trailing whitespace and quotes
    value=$(echo "$value" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//")
    # Export the variable
    export "$key=$value"
done < .env
set +a

# Prepare environment variables JSON
ENV_VARS=$(cat <<EOF
{
  "Variables": {
    "EXOTEL_API_KEY": "${EXOTEL_API_KEY}",
    "EXOTEL_API_TOKEN": "${EXOTEL_API_TOKEN}",
    "EXOTEL_SID": "${EXOTEL_SID}",
    "EXOTEL_ACCOUNT_SID": "${EXOTEL_ACCOUNT_SID}",
    "EXOPHONE_NUMBER": "${EXOPHONE_NUMBER}",
    "INFOBIP_API_KEY": "${INFOBIP_API_KEY}",
    "INFOBIP_BASE_URL": "${INFOBIP_BASE_URL}",
    "INFOBIP_FROM_EMAIL": "${INFOBIP_FROM_EMAIL}",
    "INFOBIP_FROM_NAME": "${INFOBIP_FROM_NAME}",
    "RECIPIENT_EMAIL": "${RECIPIENT_EMAIL}",
    "DB_HOST": "${DB_HOST}",
    "DB_PORT": "${DB_PORT}",
    "DB_NAME": "${DB_NAME}",
    "DB_USER": "${DB_USER}",
    "DB_PASSWORD": "${DB_PASSWORD}"
  }
}
EOF
)

echo "Updating environment variables for Lambda function: $FUNCTION_NAME"

# Update Lambda function environment variables
aws lambda update-function-configuration \
  --function-name $FUNCTION_NAME \
  --environment "$ENV_VARS" \
  --region $REGION \
  --no-cli-pager > /dev/null

echo "Environment variables set successfully!"
echo ""
echo "Configured variables:"
echo "  - EXOTEL_API_KEY"
echo "  - EXOTEL_API_TOKEN"
echo "  - EXOTEL_SID"
echo "  - EXOTEL_ACCOUNT_SID"
echo "  - EXOPHONE_NUMBER"
echo "  - INFOBIP_API_KEY"
echo "  - INFOBIP_BASE_URL"
echo "  - INFOBIP_FROM_EMAIL"
echo "  - INFOBIP_FROM_NAME"
echo "  - RECIPIENT_EMAIL"
echo "  - DB_HOST"
echo "  - DB_PORT"
echo "  - DB_NAME"
echo "  - DB_USER"
echo "  - DB_PASSWORD"
echo ""
echo "Note: Environment variables are encrypted at rest by AWS"
