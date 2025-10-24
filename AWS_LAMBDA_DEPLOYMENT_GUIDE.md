# AWS Lambda Deployment Guide - Exotel Analytics

Complete step-by-step guide to deploy your Exotel Analytics email reports on AWS Lambda with scheduled execution.

## 📋 Prerequisites

1. **AWS Account** - Sign up at https://aws.amazon.com
2. **AWS CLI installed** - Install from https://aws.amazon.com/cli/
3. **AWS credentials configured** - Run `aws configure`
4. **Python 3.10** installed locally
5. **Your .env file** with all credentials filled

## 🚀 Quick Start (3 Simple Steps)

### Step 1: Deploy Lambda Function
```bash
./deploy_lambda.sh
```
This will:
- Create a deployment package with all dependencies
- Create IAM role with necessary permissions
- Deploy Lambda function to AWS
- Takes ~2-3 minutes

### Step 2: Set Environment Variables
```bash
./set_lambda_env.sh
```
This will:
- Read your .env file
- Upload all credentials to AWS Lambda (encrypted)
- Takes ~10 seconds

### Step 3: Schedule Daily Reports
```bash
./schedule_lambda.sh
```
This will:
- Ask you what time you want daily reports (e.g., 09:30 AM IST)
- Create EventBridge schedule
- Configure automatic execution
- Takes ~30 seconds

**That's it! You're done!** 🎉

---

## 📖 Detailed Step-by-Step Guide

### Before You Start

1. **Verify AWS CLI is installed:**
```bash
aws --version
```
Expected output: `aws-cli/2.x.x Python/3.x.x ...`

2. **Configure AWS credentials:**
```bash
aws configure
```
You'll need:
- AWS Access Key ID
- AWS Secret Access Key
- Default region: `ap-south-1` (Mumbai) or your preferred region
- Default output format: `json`

**Where to get AWS credentials:**
- Go to AWS Console → IAM → Users → Your User → Security Credentials
- Click "Create Access Key"

3. **Verify your .env file has all required variables:**
```bash
cat .env
```
Must include:
- EXOTEL_API_KEY
- EXOTEL_API_TOKEN
- EXOTEL_ACCOUNT_SID
- INFOBIP_API_KEY
- INFOBIP_FROM_EMAIL
- RECIPIENT_EMAIL

---

### STEP 1: Deploy Lambda Function

Run the deployment script:
```bash
./deploy_lambda.sh
```

**What happens:**
1. Creates `lambda_package/` directory
2. Installs Python dependencies (requests, pandas, pytz)
3. Creates `lambda_deployment.zip` (~15-20MB)
4. Creates IAM role `exotel-lambda-execution-role`
5. Creates Lambda function `exotel-analytics-scheduler`

**Expected output:**
```
==========================================
AWS Lambda Deployment Script
==========================================

Step 1: Creating deployment package...
Installing Python dependencies...
Copying Lambda handler...
Creating ZIP file...
Deployment package created: lambda_deployment.zip (18MB)

Step 2: Checking IAM role...
Creating IAM role 'exotel-lambda-execution-role'...
IAM role created: arn:aws:iam::123456789012:role/exotel-lambda-execution-role

Step 3: Deploying Lambda function...
Creating new Lambda function 'exotel-analytics-scheduler'...
Lambda function created successfully!

==========================================
Deployment Complete!
==========================================
```

**Troubleshooting:**
- **Error: "AWS CLI is not installed"** → Install from https://aws.amazon.com/cli/
- **Error: "AWS credentials not configured"** → Run `aws configure`
- **Error: "Access denied"** → Your AWS user needs IAM and Lambda permissions

---

### STEP 2: Set Environment Variables

Run the environment setup script:
```bash
./set_lambda_env.sh
```

**What happens:**
- Reads your `.env` file
- Encrypts and uploads all credentials to AWS Lambda
- Variables are stored securely in AWS

**Expected output:**
```
Setting Lambda Environment Variables

Updating environment variables for Lambda function: exotel-analytics-scheduler
Environment variables set successfully!

Configured variables:
  - EXOTEL_API_KEY
  - EXOTEL_API_TOKEN
  - EXOTEL_SID
  - EXOTEL_ACCOUNT_SID
  - EXOPHONE_NUMBER
  - INFOBIP_API_KEY
  - INFOBIP_BASE_URL
  - INFOBIP_FROM_EMAIL
  - INFOBIP_FROM_NAME
  - RECIPIENT_EMAIL

Note: Environment variables are encrypted at rest by AWS
```

**To verify in AWS Console:**
1. Go to AWS Lambda Console
2. Click on function `exotel-analytics-scheduler`
3. Go to "Configuration" tab → "Environment variables"
4. You should see all 10 variables listed

---

### STEP 3: Schedule Daily Reports

Run the scheduling script:
```bash
./schedule_lambda.sh
```

**Interactive prompts:**
```
Creating EventBridge Schedule for Lambda

Enter the time (IST) when you want to receive daily reports
Format: HH:MM (24-hour format)
Example: 09:30 for 9:30 AM IST

Time (IST): 09:30

Schedule Configuration:
  IST Time: 09:30
  UTC Time: 04:00
  Cron Expression: cron(0 4 * * ? *)

Continue? (y/n): y
```

**What happens:**
1. Converts IST time to UTC (AWS uses UTC)
2. Creates EventBridge rule with cron expression
3. Grants EventBridge permission to invoke Lambda
4. Adds Lambda as the rule target

**Expected output:**
```
Step 1: Creating EventBridge rule...
EventBridge rule created

Step 2: Adding Lambda permission...
Lambda permission added

Step 3: Adding Lambda as target...
Lambda function added as target

==========================================
Schedule Created Successfully!
==========================================

Rule Name: exotel-daily-report-schedule
Schedule: Daily at 09:30 IST (04:00 UTC)
Target: exotel-analytics-scheduler
Status: ENABLED

Your Lambda function will now run automatically every day!
```

---

## ✅ Testing Your Deployment

### Test 1: Manual Invocation

Test the Lambda function manually:
```bash
aws lambda invoke \
  --function-name exotel-analytics-scheduler \
  --region ap-south-1 \
  output.json

cat output.json
```

**Expected response:**
```json
{
  "statusCode": 200,
  "body": "{\"message\": \"Report sent successfully\", \"date_range\": \"2025-10-20 to 2025-10-20\", \"total_calls\": 150, \"email_sent_to\": \"your-email@example.com\"}"
}
```

**Check your email** - You should receive the report within 1-2 minutes.

### Test 2: View Logs

Check Lambda execution logs:
```bash
aws logs tail /aws/lambda/exotel-analytics-scheduler \
  --region ap-south-1 \
  --follow
```

Or in AWS Console:
1. Go to Lambda → Functions → exotel-analytics-scheduler
2. Click "Monitor" tab → "View CloudWatch logs"
3. Click the latest log stream

---

## 📊 Monitoring & Management

### View Scheduled Executions

**AWS Console:**
1. Go to EventBridge → Rules
2. Find rule: `exotel-daily-report-schedule`
3. Click to see details and execution history

**CLI:**
```bash
aws events describe-rule \
  --name exotel-daily-report-schedule \
  --region ap-south-1
```

### Disable Schedule (Temporarily)

```bash
aws events disable-rule \
  --name exotel-daily-report-schedule \
  --region ap-south-1
```

### Enable Schedule Again

```bash
aws events enable-rule \
  --name exotel-daily-report-schedule \
  --region ap-south-1
```

### Update Environment Variables

Edit your `.env` file, then run:
```bash
./set_lambda_env.sh
```

### Change Schedule Time

Run the scheduling script again:
```bash
./schedule_lambda.sh
```
It will update the existing schedule.

### View Lambda Metrics

```bash
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Invocations \
  --dimensions Name=FunctionName,Value=exotel-analytics-scheduler \
  --start-time $(date -u -d '7 days ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 86400 \
  --statistics Sum \
  --region ap-south-1
```

---

## 💰 Cost Estimation

**AWS Lambda Free Tier (First 12 months):**
- 1 million requests per month - FREE
- 400,000 GB-seconds of compute - FREE

**Your usage (1 execution per day):**
- Requests: ~30 per month
- Duration: ~10-30 seconds per execution
- Memory: 512 MB

**Cost: $0.00** (well within free tier) ✅

**After free tier:**
- Requests: $0.20 per million
- Compute: $0.0000166667 per GB-second
- **Estimated: ~$0.01/month** (basically free)

---

## 🔧 Troubleshooting

### Issue: "No calls found"
**Solution:**
- Check your Exotel API credentials in `.env`
- Verify date range (Lambda fetches yesterday's data by default)
- Check if there were actual calls yesterday

### Issue: "Failed to send email"
**Solution:**
- Verify Infobip API key is correct
- Check `INFOBIP_FROM_EMAIL` is a verified sender in Infobip
- Check Lambda logs for detailed error message

### Issue: "Environment variables not set"
**Solution:**
```bash
./set_lambda_env.sh
```

### Issue: Lambda timeout
**Solution:**
The timeout is set to 300 seconds (5 minutes). If you need more:
```bash
aws lambda update-function-configuration \
  --function-name exotel-analytics-scheduler \
  --timeout 600 \
  --region ap-south-1
```

### Issue: Schedule not triggering
**Solutions:**
1. Verify EventBridge rule is enabled:
```bash
aws events describe-rule --name exotel-daily-report-schedule --region ap-south-1
```

2. Check Lambda permissions:
```bash
aws lambda get-policy --function-name exotel-analytics-scheduler --region ap-south-1
```

3. View EventBridge metrics in CloudWatch

---

## 🔐 Security Best Practices

1. **Never commit credentials** - `.env` is in `.gitignore`
2. **Use IAM roles** - Scripts create minimal permission roles
3. **Encrypt environment variables** - AWS encrypts them at rest automatically
4. **Use AWS Secrets Manager** (optional, for enhanced security):
```bash
# Store secret in AWS Secrets Manager
aws secretsmanager create-secret \
  --name exotel/api-credentials \
  --secret-string file://.env \
  --region ap-south-1
```

5. **Enable CloudTrail** - Audit all Lambda executions
6. **Set up CloudWatch Alarms** - Get notified on failures

---

## 🗑️ Cleanup (Deleting Everything)

To remove all AWS resources:

```bash
# Delete EventBridge rule
aws events remove-targets --rule exotel-daily-report-schedule --ids 1 --region ap-south-1
aws events delete-rule --name exotel-daily-report-schedule --region ap-south-1

# Delete Lambda function
aws lambda delete-function --function-name exotel-analytics-scheduler --region ap-south-1

# Delete IAM role
aws iam detach-role-policy --role-name exotel-lambda-execution-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
aws iam delete-role --role-name exotel-lambda-execution-role

# Clean up local files
rm -rf lambda_package lambda_deployment.zip output.json
```

---

## 📞 Support

### Common Questions

**Q: Can I schedule multiple times per day?**
A: Yes! Create multiple EventBridge rules, each with different cron expressions.

**Q: Can I send to multiple recipients?**
A: Yes! Update `RECIPIENT_EMAIL` to comma-separated: `email1@example.com,email2@example.com`

**Q: How do I update the Lambda code?**
A: Just run `./deploy_lambda.sh` again. It will update the existing function.

**Q: Can I test with a specific date?**
A: Yes! Invoke with custom event:
```bash
echo '{"date": "2025-10-15"}' > event.json
aws lambda invoke --function-name exotel-analytics-scheduler \
  --payload file://event.json --region ap-south-1 output.json
```

**Q: How do I view execution history?**
A: AWS Console → Lambda → Functions → exotel-analytics-scheduler → Monitor → "Invocations" graph

**Q: Can I change the AWS region?**
A: Yes! Edit the `REGION` variable in all `.sh` scripts before running them.

---

## 📚 Additional Resources

- **AWS Lambda Documentation**: https://docs.aws.amazon.com/lambda/
- **EventBridge Cron Expressions**: https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-create-rule-schedule.html
- **Exotel API Docs**: https://developer.exotel.com/api/
- **Infobip Email API**: https://www.infobip.com/docs/api#channels/email

---

## 🎯 What You've Achieved

✅ Serverless email reporting (no server to maintain)
✅ Automated daily execution (set it and forget it)
✅ Secure credential storage (encrypted by AWS)
✅ Scalable solution (handles any call volume)
✅ Cost-effective (~$0/month with free tier)
✅ Monitoring & logging (CloudWatch integration)

**You no longer need to manually click buttons!** Your reports will arrive automatically every day. 📧🎉
