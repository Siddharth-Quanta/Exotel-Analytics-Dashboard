"""
AWS Lambda Handler for Exotel Analytics Scheduled Email Reports

This Lambda function fetches call analytics from Exotel API and sends
automated email reports via Infobip Email API.

Triggered by: AWS EventBridge (CloudWatch Events) on a schedule
"""

import os
import json
import logging
from datetime import datetime, timedelta
import requests
import pandas as pd
import pytz
from tenant_lookup import get_tenant_lookup

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)


class ExotelAnalytics:
    """Exotel API integration for call analytics"""

    def __init__(self, api_key, api_token, sid, account_sid):
        self.api_key = api_key
        self.api_token = api_token
        self.sid = sid
        self.account_sid = account_sid
        self.base_url = f"https://api.exotel.com/v1/Accounts/{account_sid}"

    def fetch_calls(self, start_date, end_date):
        """Fetch calls from Exotel API with pagination support"""
        try:
            all_calls = []
            url = f"{self.base_url}/Calls.json"

            # Format dates for Exotel API
            start_time = datetime.strptime(start_date, '%Y-%m-%d').strftime('%Y-%m-%d 00:00:00')
            end_time = (datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)).strftime('%Y-%m-%d 23:59:59')
            date_filter = f"gte:{start_time};lte:{end_time}"

            params = {
                'DateCreated': date_filter,
                'PageSize': 100,
                'SortBy': 'DateCreated:desc'
            }

            logger.info(f"Fetching calls from {start_date} to {end_date}")

            page = 1
            while True:
                response = requests.get(
                    url,
                    auth=(self.api_key, self.api_token),
                    params=params,
                    timeout=30
                )

                if response.status_code == 200:
                    data = response.json()
                    calls = data.get('Calls', [])

                    if not calls:
                        break

                    all_calls.extend(calls)
                    logger.info(f"Fetched page {page}: {len(calls)} calls (Total: {len(all_calls)})")

                    # Check for next page
                    metadata = data.get('Metadata', {})
                    next_page_uri = metadata.get('NextPageUri')

                    if not next_page_uri:
                        break

                    url = f"https://api.exotel.com{next_page_uri}"
                    params = {}
                    page += 1
                else:
                    logger.error(f"API request failed: {response.status_code} - {response.text}")
                    break

            logger.info(f"Successfully fetched {len(all_calls)} calls")
            return all_calls

        except Exception as e:
            logger.error(f"Error fetching calls: {str(e)}")
            return []

    def process_analytics(self, calls, exophone_filter=None):
        """Process call data into analytics with Service/Enquiry categorization"""
        if not calls:
            logger.warning("No calls data to process")
            return None

        try:
            df = pd.DataFrame(calls)

            # Filter by exophone number if specified
            if exophone_filter and ('PhoneNumber' in df.columns or 'To' in df.columns):
                logger.info(f"Filtering calls for exophone: {exophone_filter}")
                initial_count = len(df)

                # Extract last 10 digits for flexible matching
                filter_digits = ''.join(filter(str.isdigit, exophone_filter))[-10:]

                # Filter by PhoneNumber or To field containing the exophone digits
                def matches_exophone(row):
                    phone_num = str(row.get('PhoneNumber', ''))
                    to_num = str(row.get('To', ''))
                    return filter_digits in phone_num or filter_digits in to_num

                df = df[df.apply(matches_exophone, axis=1)]
                logger.info(f"Filtered from {initial_count} to {len(df)} calls")

            if len(df) == 0:
                logger.warning("No calls found after filtering")
                return None

            # Convert datetime strings
            if 'DateCreated' in df.columns:
                df['DateCreated'] = pd.to_datetime(df['DateCreated'])
                df['Date'] = df['DateCreated'].dt.date
                df['Hour'] = df['DateCreated'].dt.hour

            # ==================== NEW: Service vs Enquiry Categorization ====================
            # Get tenant lookup instance
            tenant_lookup = get_tenant_lookup()

            # Categorize incoming calls as Service or Enquiry
            if 'Direction' in df.columns and 'From' in df.columns:
                # Filter only incoming calls
                incoming_df = df[df['Direction'] == 'inbound'].copy()

                if len(incoming_df) > 0:
                    # Get unique phone numbers
                    phone_numbers = incoming_df['From'].unique().tolist()

                    # Batch lookup (more efficient than one-by-one)
                    lookup_results = tenant_lookup.batch_lookup(phone_numbers)

                    # Map results back to dataframe
                    def categorize_call(phone):
                        is_tenant, call_type, info = lookup_results.get(phone, (False, 'enquiry', None))
                        return call_type

                    incoming_df['call_category'] = incoming_df['From'].apply(categorize_call)

                    # Merge back into main dataframe
                    df = df.merge(incoming_df[['Sid', 'call_category']], on='Sid', how='left')

                    # Fill non-incoming calls with 'outgoing'
                    df['call_category'] = df['call_category'].fillna('outgoing')

                    logger.info(f"Categorized {len(incoming_df)} incoming calls")
                else:
                    df['call_category'] = 'outgoing'
            else:
                df['call_category'] = 'unknown'
            # ==================== END Categorization ====================

            # Calculate metrics
            analytics = {
                'total_calls': len(df),
                'incoming_calls': len(df[df['Direction'] == 'inbound']) if 'Direction' in df.columns else 0,
                'outgoing_calls': len(df[df['Direction'].str.startswith('outbound', na=False)]) if 'Direction' in df.columns else 0,
                'answered_calls': len(df[df['Status'] == 'completed']) if 'Status' in df.columns else 0,
                'missed_calls': len(df[(df['Status'] == 'no-answer') | (df['Status'] == 'failed') | (df['Status'] == 'busy')]) if 'Status' in df.columns else 0,
                'avg_duration': df['Duration'].mean() if 'Duration' in df.columns else 0,
                'daily_calls': df.groupby('Date').size().to_dict() if 'Date' in df.columns else {},
                'hourly_calls': df.groupby('Hour').size().to_dict() if 'Hour' in df.columns else {},
                'status_breakdown': df['Status'].value_counts().to_dict() if 'Status' in df.columns else {},
                'direction_breakdown': df['Direction'].value_counts().to_dict() if 'Direction' in df.columns else {},

                # ==================== NEW: Service vs Enquiry Metrics ====================
                'service_calls': len(df[df['call_category'] == 'service']) if 'call_category' in df.columns else 0,
                'enquiry_calls': len(df[df['call_category'] == 'enquiry']) if 'call_category' in df.columns else 0,
                'service_percentage': 0,
                'enquiry_percentage': 0,
                'category_breakdown': df['call_category'].value_counts().to_dict() if 'call_category' in df.columns else {}
                # ==================== END New Metrics ====================
            }

            # Calculate percentages
            if analytics['incoming_calls'] > 0:
                analytics['service_percentage'] = round((analytics['service_calls'] / analytics['incoming_calls']) * 100, 1)
                analytics['enquiry_percentage'] = round((analytics['enquiry_calls'] / analytics['incoming_calls']) * 100, 1)

            # Convert date objects to strings for JSON serialization
            if analytics['daily_calls']:
                analytics['daily_calls'] = {str(k): v for k, v in analytics['daily_calls'].items()}

            return analytics

        except Exception as e:
            logger.error(f"Error processing analytics: {str(e)}")
            return None


def send_email_via_infobip(analytics, start_date, end_date, config):
    """Send analytics report via Infobip Email API"""
    try:
        api_key = config['infobip_api_key']
        base_url = config['infobip_base_url']
        from_email = config['infobip_from_email']
        from_name = config['infobip_from_name']
        recipient = config['recipient_email']

        if not all([api_key, base_url, from_email, recipient]):
            logger.error("Infobip configuration incomplete")
            return False

        # Prepare email content
        subject = f"📊 Daily Exotel Analytics Report - {start_date}"

        # HTML email body with enhanced styling
        html_content = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; background-color: #f5f5f5; }}
                .container {{ max-width: 800px; margin: 0 auto; background: white; border-radius: 10px; overflow: hidden; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
                .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; text-align: center; }}
                .header h1 {{ margin: 0; font-size: 28px; }}
                .header p {{ margin: 10px 0 0 0; opacity: 0.9; }}
                .content {{ padding: 30px; }}
                .metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin: 20px 0; }}
                .metric-card {{
                    border: 1px solid #e0e0e0;
                    border-radius: 8px;
                    padding: 20px;
                    text-align: center;
                    background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }}
                .metric-value {{ font-size: 42px; font-weight: bold; color: #667eea; margin-bottom: 10px; }}
                .metric-label {{ font-size: 14px; color: #666; text-transform: uppercase; letter-spacing: 1px; }}
                .footer {{ background: #f9f9f9; padding: 20px; text-align: center; color: #666; font-size: 14px; }}
                .date-badge {{ display: inline-block; background: #fff; color: #667eea; padding: 5px 15px; border-radius: 20px; font-size: 14px; margin-top: 10px; }}
                .breakdown {{ margin: 30px 0; padding: 20px; background: #f9f9f9; border-radius: 8px; }}
                .breakdown h3 {{ color: #667eea; margin-bottom: 15px; }}
                .breakdown-item {{ display: flex; justify-content: space-between; padding: 10px; border-bottom: 1px solid #e0e0e0; }}
                .breakdown-item:last-child {{ border-bottom: none; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>📊 Daily Call Analytics Report</h1>
                    <p>Exotel Analytics Dashboard</p>
                    <div class="date-badge">Report Date: {start_date}</div>
                </div>

                <div class="content">
                    <h2 style="color: #667eea; margin-bottom: 20px;">Key Metrics</h2>
                    <div class="metrics">
                        <div class="metric-card">
                            <div class="metric-value">{analytics['total_calls']}</div>
                            <div class="metric-label">Total Calls</div>
                        </div>
                        <div class="metric-card">
                            <div class="metric-value">{analytics['incoming_calls']}</div>
                            <div class="metric-label">Incoming Calls</div>
                        </div>
                        <div class="metric-card">
                            <div class="metric-value">{analytics['outgoing_calls']}</div>
                            <div class="metric-label">Outgoing Calls</div>
                        </div>
                        <div class="metric-card">
                            <div class="metric-value">{analytics['answered_calls']}</div>
                            <div class="metric-label">Answered Calls</div>
                        </div>
                        <div class="metric-card">
                            <div class="metric-value">{analytics['missed_calls']}</div>
                            <div class="metric-label">Missed Calls</div>
                        </div>
                        <div class="metric-card">
                            <div class="metric-value">{int(analytics['avg_duration'])}s</div>
                            <div class="metric-label">Avg Duration</div>
                        </div>
                    </div>

                    <h2 style="color: #667eea; margin: 30px 0 20px 0;">📊 Call Categorization</h2>
                    <div class="metrics">
                        <div class="metric-card" style="background: linear-gradient(135deg, #d4edda 0%, #c3e6cb 100%);">
                            <div class="metric-value" style="color: #4CAF50;">🔧 {analytics.get('service_calls', 0)}</div>
                            <div class="metric-label">Service Calls ({analytics.get('service_percentage', 0)}%)</div>
                            <div style="font-size: 11px; color: #666; margin-top: 5px;">Existing tenants</div>
                        </div>
                        <div class="metric-card" style="background: linear-gradient(135deg, #fff3cd 0%, #ffe9a3 100%);">
                            <div class="metric-value" style="color: #FF9800;">💡 {analytics.get('enquiry_calls', 0)}</div>
                            <div class="metric-label">Enquiry Calls ({analytics.get('enquiry_percentage', 0)}%)</div>
                            <div style="font-size: 11px; color: #666; margin-top: 5px;">New prospects!</div>
                        </div>
                    </div>

                    <div class="breakdown">
                        <h3>Call Status Breakdown</h3>
                        {''.join([f'<div class="breakdown-item"><span>{status}</span><span><strong>{count}</strong></span></div>'
                                  for status, count in analytics.get('status_breakdown', {}).items()])}
                    </div>

                    <div class="breakdown">
                        <h3>Call Direction Breakdown</h3>
                        {''.join([f'<div class="breakdown-item"><span>{direction}</span><span><strong>{count}</strong></span></div>'
                                  for direction, count in analytics.get('direction_breakdown', {}).items()])}
                    </div>
                </div>

                <div class="footer">
                    <p><strong>Automated Daily Report</strong></p>
                    <p>Generated on {datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%B %d, %Y at %I:%M %p IST')}</p>
                    <p style="margin-top: 15px;">Powered by AWS Lambda</p>
                </div>
            </div>
        </body>
        </html>
        """

        # Prepare API request
        url = f"{base_url}/email/3/send"

        data = {
            "from": f"{from_name} <{from_email}>",
            "to": recipient,
            "subject": subject,
            "html": html_content,
        }

        headers = {
            "Authorization": api_key if api_key.startswith("App ") else f"App {api_key}",
        }

        logger.info(f"Sending email to {recipient}")

        # Send request with dummy files to force multipart/form-data
        dummy_files = {'dummy': ('', '')}
        response = requests.post(url, headers=headers, data=data, files=dummy_files, timeout=30)

        logger.info(f"Infobip response status: {response.status_code}")

        if 200 <= response.status_code < 300:
            logger.info(f"Email sent successfully to {recipient}")
            return True
        else:
            logger.error(f"Infobip API error: {response.status_code} - {response.text}")
            return False

    except Exception as e:
        logger.error(f"Error sending email via Infobip: {str(e)}")
        return False


def lambda_handler(event, context):
    """
    AWS Lambda handler function

    Triggered by EventBridge on a schedule
    Fetches yesterday's call data and sends email report

    Args:
        event: EventBridge event (contains schedule info)
        context: Lambda context object

    Returns:
        dict: Status response
    """
    try:
        logger.info("Lambda function started")
        logger.info(f"Event: {json.dumps(event)}")

        # Get configuration from environment variables
        config = {
            'exotel_api_key': os.environ.get('EXOTEL_API_KEY'),
            'exotel_api_token': os.environ.get('EXOTEL_API_TOKEN'),
            'exotel_sid': os.environ.get('EXOTEL_SID'),
            'exotel_account_sid': os.environ.get('EXOTEL_ACCOUNT_SID'),
            'exophone_number': os.environ.get('EXOPHONE_NUMBER', ''),
            'infobip_api_key': os.environ.get('INFOBIP_API_KEY'),
            'infobip_base_url': os.environ.get('INFOBIP_BASE_URL', 'https://api.infobip.com'),
            'infobip_from_email': os.environ.get('INFOBIP_FROM_EMAIL'),
            'infobip_from_name': os.environ.get('INFOBIP_FROM_NAME', 'Exotel Analytics'),
            'recipient_email': os.environ.get('RECIPIENT_EMAIL'),
        }

        # Validate required config
        required_fields = ['exotel_api_key', 'exotel_api_token', 'exotel_account_sid',
                          'infobip_api_key', 'infobip_from_email', 'recipient_email']
        missing_fields = [field for field in required_fields if not config.get(field)]

        if missing_fields:
            error_msg = f"Missing required environment variables: {', '.join(missing_fields)}"
            logger.error(error_msg)
            return {
                'statusCode': 500,
                'body': json.dumps({'error': error_msg})
            }

        # Use IST timezone
        ist = pytz.timezone('Asia/Kolkata')
        now_ist = datetime.now(ist)

        # Get yesterday's data (or custom date from event if provided)
        if 'date' in event:
            # Allow custom date from event
            target_date = event['date']
            start_date = target_date
            end_date = target_date
        else:
            # Default: yesterday's data
            yesterday = now_ist - timedelta(days=1)
            start_date = yesterday.strftime('%Y-%m-%d')
            end_date = yesterday.strftime('%Y-%m-%d')

        logger.info(f"Fetching report for date: {start_date} to {end_date}")

        # Initialize Exotel client
        exotel = ExotelAnalytics(
            config['exotel_api_key'],
            config['exotel_api_token'],
            config.get('exotel_sid', ''),
            config['exotel_account_sid']
        )

        # Fetch calls
        calls = exotel.fetch_calls(start_date, end_date)

        if not calls:
            logger.warning("No call data retrieved from Exotel API")
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'No calls found for the specified date range',
                    'date_range': f"{start_date} to {end_date}"
                })
            }

        # Process analytics
        exophone_filter = config.get('exophone_number')
        analytics = exotel.process_analytics(calls, exophone_filter=exophone_filter)

        if not analytics:
            logger.warning("Failed to process analytics")
            return {
                'statusCode': 500,
                'body': json.dumps({'error': 'Failed to process analytics'})
            }

        # Send email report
        email_sent = send_email_via_infobip(analytics, start_date, end_date, config)

        if email_sent:
            logger.info("Report generated and sent successfully")
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'Report sent successfully',
                    'date_range': f"{start_date} to {end_date}",
                    'total_calls': analytics['total_calls'],
                    'email_sent_to': config['recipient_email']
                })
            }
        else:
            logger.error("Failed to send email")
            return {
                'statusCode': 500,
                'body': json.dumps({'error': 'Failed to send email report'})
            }

    except Exception as e:
        logger.error(f"Lambda execution failed: {str(e)}", exc_info=True)
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }


# For local testing
if __name__ == "__main__":
    # Load environment variables from .env for local testing
    from dotenv import load_dotenv
    load_dotenv()

    # Simulate Lambda event
    test_event = {}
    test_context = {}

    result = lambda_handler(test_event, test_context)
    print(json.dumps(result, indent=2))
