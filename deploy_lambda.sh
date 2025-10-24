#!/bin/bash

# AWS Lambda Deployment Script for Exotel Analytics
# This script creates a deployment package and uploads it to AWS Lambda

set -e  # Exit on error

echo "=========================================="
echo "AWS Lambda Deployment Script"
echo "=========================================="
echo ""

# Configuration
FUNCTION_NAME="exotel-analytics-scheduler"
RUNTIME="python3.10"
HANDLER="lambda_handler.lambda_handler"
ROLE_NAME="exotel-lambda-execution-role"
MEMORY_SIZE=512  # MB
TIMEOUT=300      # 5 minutes (max time for execution)
REGION="ap-south-1"  # Mumbai region (change as needed)

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if AWS CLI is installed
if ! command -v aws &> /dev/null; then
    echo -e "${RED}Error: AWS CLI is not installed${NC}"
    echo "Install it from: https://aws.amazon.com/cli/"
    exit 1
fi

# Check if AWS credentials are configured
if ! aws sts get-caller-identity &> /dev/null; then
    echo -e "${RED}Error: AWS credentials not configured${NC}"
    echo "Run: aws configure"
    exit 1
fi

echo -e "${GREEN}Step 1: Creating deployment package...${NC}"

# Create a clean directory for the package
rm -rf lambda_package
mkdir -p lambda_package

# Install dependencies to the package directory
echo "Installing Python dependencies..."
pip install -r requirements-lambda.txt -t lambda_package/ --quiet

# Copy the Lambda handler and tenant lookup module
echo "Copying Lambda handler and tenant lookup module..."
cp lambda_handler.py lambda_package/
cp tenant_lookup.py lambda_package/

# Create the deployment zip file
echo "Creating ZIP file..."
cd lambda_package
zip -r ../lambda_deployment.zip . -q
cd ..

# Get the size of the deployment package
PACKAGE_SIZE=$(du -h lambda_deployment.zip | cut -f1)
echo -e "${GREEN}Deployment package created: lambda_deployment.zip ($PACKAGE_SIZE)${NC}"
echo ""

# Check if IAM role exists, create if not
echo -e "${GREEN}Step 2: Checking IAM role...${NC}"
if aws iam get-role --role-name $ROLE_NAME --region $REGION &> /dev/null; then
    echo "IAM role '$ROLE_NAME' already exists"
    ROLE_ARN=$(aws iam get-role --role-name $ROLE_NAME --region $REGION --query 'Role.Arn' --output text)
else
    echo "Creating IAM role '$ROLE_NAME'..."

    # Create trust policy
    cat > trust-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "lambda.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

    # Create the role
    ROLE_ARN=$(aws iam create-role \
        --role-name $ROLE_NAME \
        --assume-role-policy-document file://trust-policy.json \
        --region $REGION \
        --query 'Role.Arn' \
        --output text)

    # Attach basic Lambda execution policy
    aws iam attach-role-policy \
        --role-name $ROLE_NAME \
        --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole \
        --region $REGION

    echo -e "${GREEN}IAM role created: $ROLE_ARN${NC}"
    echo -e "${YELLOW}Waiting 10 seconds for IAM role to propagate...${NC}"
    sleep 10

    rm trust-policy.json
fi
echo ""

# Check if Lambda function exists
echo -e "${GREEN}Step 3: Deploying Lambda function...${NC}"
if aws lambda get-function --function-name $FUNCTION_NAME --region $REGION &> /dev/null; then
    echo "Lambda function '$FUNCTION_NAME' exists. Updating code..."

    aws lambda update-function-code \
        --function-name $FUNCTION_NAME \
        --zip-file fileb://lambda_deployment.zip \
        --region $REGION \
        --no-cli-pager > /dev/null

    echo "Waiting for code update to complete..."
    aws lambda wait function-updated \
        --function-name $FUNCTION_NAME \
        --region $REGION

    echo "Updating configuration..."
    aws lambda update-function-configuration \
        --function-name $FUNCTION_NAME \
        --runtime $RUNTIME \
        --handler $HANDLER \
        --memory-size $MEMORY_SIZE \
        --timeout $TIMEOUT \
        --region $REGION \
        --no-cli-pager > /dev/null

    echo -e "${GREEN}Lambda function updated successfully!${NC}"
else
    echo "Creating new Lambda function '$FUNCTION_NAME'..."

    aws lambda create-function \
        --function-name $FUNCTION_NAME \
        --runtime $RUNTIME \
        --role $ROLE_ARN \
        --handler $HANDLER \
        --zip-file fileb://lambda_deployment.zip \
        --memory-size $MEMORY_SIZE \
        --timeout $TIMEOUT \
        --region $REGION \
        --no-cli-pager > /dev/null

    echo -e "${GREEN}Lambda function created successfully!${NC}"
fi
echo ""

# Display next steps
echo -e "${GREEN}=========================================="
echo "Deployment Complete!"
echo "==========================================${NC}"
echo ""
echo "Function Name: $FUNCTION_NAME"
echo "Region: $REGION"
echo "Runtime: $RUNTIME"
echo "Memory: ${MEMORY_SIZE}MB"
echo "Timeout: ${TIMEOUT}s"
echo ""
echo -e "${YELLOW}NEXT STEPS:${NC}"
echo ""
echo "1. Set environment variables in AWS Lambda Console:"
echo "   - EXOTEL_API_KEY"
echo "   - EXOTEL_API_TOKEN"
echo "   - EXOTEL_ACCOUNT_SID"
echo "   - EXOPHONE_NUMBER (optional)"
echo "   - INFOBIP_API_KEY"
echo "   - INFOBIP_FROM_EMAIL"
echo "   - INFOBIP_FROM_NAME"
echo "   - RECIPIENT_EMAIL"
echo "   - DB_HOST (for tenant lookup)"
echo "   - DB_PORT (for tenant lookup)"
echo "   - DB_NAME (for tenant lookup)"
echo "   - DB_USER (for tenant lookup)"
echo "   - DB_PASSWORD (for tenant lookup)"
echo ""
echo "   OR run: ./set_lambda_env.sh"
echo ""
echo "2. Create EventBridge rule for scheduling:"
echo "   - Go to AWS EventBridge Console"
echo "   - Create a new rule with cron expression"
echo "   - Set target as this Lambda function"
echo ""
echo "   OR run: ./schedule_lambda.sh"
echo ""
echo "3. Test the function:"
echo "   aws lambda invoke --function-name $FUNCTION_NAME --region $REGION output.json"
echo ""
echo -e "${GREEN}Cleanup: You can delete lambda_package/ and lambda_deployment.zip${NC}"
