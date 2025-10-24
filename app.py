from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import requests
from datetime import datetime, timedelta
import pandas as pd
import plotly.graph_objs as go
import plotly.utils
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
import os
from dotenv import load_dotenv
import logging
import base64

# Import tenant lookup module for Service vs Enquiry categorization
from tenant_lookup import get_tenant_lookup

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your-secret-key-here')

# Global configuration storage
config = {
    'exotel_api_key': os.getenv('EXOTEL_API_KEY', ''),
    'exotel_api_token': os.getenv('EXOTEL_API_TOKEN', ''),
    'exotel_sid': os.getenv('EXOTEL_SID', ''),
    'exotel_account_sid': os.getenv('EXOTEL_ACCOUNT_SID', ''),
    'exophone_number': os.getenv('EXOPHONE_NUMBER', ''),  # Filter by specific exophone
    'sender_email': os.getenv('SENDER_EMAIL', ''),
    'sender_password': os.getenv('SENDER_PASSWORD', ''),
    'recipient_email': os.getenv('RECIPIENT_EMAIL', ''),
    'infobip_api_key': os.getenv('INFOBIP_API_KEY', ''),
    'infobip_base_url': os.getenv('INFOBIP_BASE_URL', 'https://api.infobip.com'),
    'infobip_from_email': os.getenv('INFOBIP_FROM_EMAIL', ''),
    'infobip_from_name': os.getenv('INFOBIP_FROM_NAME', 'Exotel Analytics'),
    'report_time': '09:30'
}

# Initialize scheduler
scheduler = BackgroundScheduler()
scheduler.start()


class ExotelAnalytics:
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

            # Format dates for Exotel API (uses DateCreated parameter)
            # Format: DateCreated=gte:YYYY-MM-DD HH:MM:SS;lte:YYYY-MM-DD HH:MM:SS
            start_time = datetime.strptime(start_date, '%Y-%m-%d').strftime('%Y-%m-%d 00:00:00')
            end_time = (datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)).strftime('%Y-%m-%d 23:59:59')

            date_filter = f"gte:{start_time};lte:{end_time}"

            params = {
                'DateCreated': date_filter,
                'PageSize': 100,  # Maximum allowed per page (Exotel limit)
                'SortBy': 'DateCreated:desc'
            }

            logger.info(f"Fetching calls from {start_date} to {end_date} (filter: {date_filter})")

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
                    logger.info(f"Fetched page {page}: {len(calls)} calls (Total so far: {len(all_calls)})")

                    # Check if there are more pages
                    metadata = data.get('Metadata', {})
                    next_page_uri = metadata.get('NextPageUri')

                    if not next_page_uri:
                        break

                    # Update URL for next page
                    url = f"https://api.exotel.com{next_page_uri}"
                    params = {}  # Clear params as they're in the URI
                    page += 1

                else:
                    logger.error(f"API request failed: {response.status_code} - {response.text}")
                    break

            logger.info(f"Successfully fetched total of {len(all_calls)} calls")
            return all_calls

        except Exception as e:
            logger.error(f"Error fetching calls: {str(e)}")
            return []

    def process_analytics(self, calls, exophone_filter=None):
        """Process call data into analytics with Service/Enquiry categorization"""
        if not calls:
            return None

        try:
            df = pd.DataFrame(calls)

            # Filter by exophone number if specified (handle multiple formats)
            if exophone_filter and ('PhoneNumber' in df.columns or 'To' in df.columns):
                logger.info(f"Filtering calls for exophone: {exophone_filter}")
                initial_count = len(df)

                # Extract last 10 digits for flexible matching (8047361499)
                filter_digits = ''.join(filter(str.isdigit, exophone_filter))[-10:]

                # Filter by PhoneNumber or To field containing the exophone digits
                def matches_exophone(row):
                    phone_num = str(row.get('PhoneNumber', ''))
                    to_num = str(row.get('To', ''))
                    return filter_digits in phone_num or filter_digits in to_num

                df = df[df.apply(matches_exophone, axis=1)]
                logger.info(f"Filtered from {initial_count} to {len(df)} calls for exophone {exophone_filter}")

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
            # Note: Exotel API returns Direction as 'inbound', 'outbound-api', 'outbound-dial'
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


def calculate_comparison(current_analytics, previous_analytics):
    """
    Calculate comparison metrics between two periods
    Returns dict with changes and percentages
    """
    comparison = {
        'total_calls_change': 0,
        'incoming_calls_change': 0,
        'service_calls_change': 0,
        'enquiry_calls_change': 0,
        'total_calls_pct': 0,
        'incoming_calls_pct': 0,
        'service_calls_pct': 0,
        'enquiry_calls_pct': 0
    }

    if not previous_analytics or not current_analytics:
        return comparison

    try:
        # Calculate absolute changes
        comparison['total_calls_change'] = current_analytics.get('total_calls', 0) - previous_analytics.get('total_calls', 0)
        comparison['incoming_calls_change'] = current_analytics.get('incoming_calls', 0) - previous_analytics.get('incoming_calls', 0)
        comparison['service_calls_change'] = current_analytics.get('service_calls', 0) - previous_analytics.get('service_calls', 0)
        comparison['enquiry_calls_change'] = current_analytics.get('enquiry_calls', 0) - previous_analytics.get('enquiry_calls', 0)

        # Calculate percentage changes
        if previous_analytics.get('total_calls', 0) > 0:
            comparison['total_calls_pct'] = round((comparison['total_calls_change'] / previous_analytics['total_calls']) * 100, 1)

        if previous_analytics.get('incoming_calls', 0) > 0:
            comparison['incoming_calls_pct'] = round((comparison['incoming_calls_change'] / previous_analytics['incoming_calls']) * 100, 1)

        if previous_analytics.get('service_calls', 0) > 0:
            comparison['service_calls_pct'] = round((comparison['service_calls_change'] / previous_analytics['service_calls']) * 100, 1)

        if previous_analytics.get('enquiry_calls', 0) > 0:
            comparison['enquiry_calls_pct'] = round((comparison['enquiry_calls_change'] / previous_analytics['enquiry_calls']) * 100, 1)

    except Exception as e:
        logger.error(f"Error calculating comparison: {e}")

    return comparison


def generate_charts(analytics):
    """Generate Plotly charts from analytics data"""
    charts = {}

    try:
        # Daily call volume chart
        if analytics['daily_calls']:
            dates = list(analytics['daily_calls'].keys())
            counts = list(analytics['daily_calls'].values())

            fig1 = go.Figure(data=[
                go.Scatter(x=dates, y=counts, mode='lines+markers', name='Calls')
            ])
            fig1.update_layout(
                title='Daily Call Volume',
                xaxis_title='Date',
                yaxis_title='Number of Calls',
                template='plotly_white'
            )
            charts['daily_volume'] = json.dumps(fig1, cls=plotly.utils.PlotlyJSONEncoder)

        # Call direction pie chart
        if analytics['direction_breakdown']:
            labels = list(analytics['direction_breakdown'].keys())
            values = list(analytics['direction_breakdown'].values())

            fig2 = go.Figure(data=[
                go.Pie(labels=labels, values=values)
            ])
            fig2.update_layout(title='Call Direction Distribution')
            charts['direction'] = json.dumps(fig2, cls=plotly.utils.PlotlyJSONEncoder)

        # Call status bar chart
        if analytics['status_breakdown']:
            statuses = list(analytics['status_breakdown'].keys())
            counts = list(analytics['status_breakdown'].values())

            fig3 = go.Figure(data=[
                go.Bar(x=statuses, y=counts)
            ])
            fig3.update_layout(
                title='Call Status Distribution',
                xaxis_title='Status',
                yaxis_title='Count',
                template='plotly_white'
            )
            charts['status'] = json.dumps(fig3, cls=plotly.utils.PlotlyJSONEncoder)

        # Hourly distribution chart
        if analytics['hourly_calls']:
            hours = sorted(analytics['hourly_calls'].keys())
            counts = [analytics['hourly_calls'][h] for h in hours]

            fig4 = go.Figure(data=[
                go.Bar(x=hours, y=counts)
            ])
            fig4.update_layout(
                title='Hourly Call Distribution',
                xaxis_title='Hour of Day',
                yaxis_title='Number of Calls',
                template='plotly_white'
            )
            charts['hourly'] = json.dumps(fig4, cls=plotly.utils.PlotlyJSONEncoder)

        # ==================== NEW: Service vs Enquiry Chart ====================
        # Service vs Enquiry pie chart (for incoming calls only)
        if analytics.get('service_calls', 0) > 0 or analytics.get('enquiry_calls', 0) > 0:
            labels = []
            values = []
            colors = []

            if analytics.get('service_calls', 0) > 0:
                labels.append(f"Service Calls ({analytics['service_percentage']}%)")
                values.append(analytics['service_calls'])
                colors.append('#4CAF50')  # Green

            if analytics.get('enquiry_calls', 0) > 0:
                labels.append(f"Enquiry Calls ({analytics['enquiry_percentage']}%)")
                values.append(analytics['enquiry_calls'])
                colors.append('#FF9800')  # Orange

            fig5 = go.Figure(data=[
                go.Pie(labels=labels, values=values, marker=dict(colors=colors))
            ])
            fig5.update_layout(
                title='Service vs Enquiry Calls (Incoming Only)',
                template='plotly_white'
            )
            charts['service_enquiry'] = json.dumps(fig5, cls=plotly.utils.PlotlyJSONEncoder)
        # ==================== END Service vs Enquiry Chart ====================

        return charts

    except Exception as e:
        logger.error(f"Error generating charts: {str(e)}")
        return {}


def send_email_report(analytics, charts):
    """Send analytics report via email"""
    try:
        sender = config['sender_email']
        password = config['sender_password']
        recipient = config['recipient_email']

        if not all([sender, password, recipient]):
            logger.error("Email configuration incomplete")
            return False

        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"Exotel Analytics Report - {datetime.now().strftime('%Y-%m-%d')}"
        msg['From'] = sender
        msg['To'] = recipient

        # HTML email body
        html = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                .header {{ background-color: #4CAF50; color: white; padding: 20px; text-align: center; }}
                .metrics {{ display: flex; flex-wrap: wrap; margin: 20px 0; }}
                .metric-card {{
                    border: 1px solid #ddd;
                    border-radius: 5px;
                    padding: 15px;
                    margin: 10px;
                    min-width: 200px;
                    background-color: #f9f9f9;
                }}
                .metric-value {{ font-size: 32px; font-weight: bold; color: #4CAF50; }}
                .metric-label {{ font-size: 14px; color: #666; margin-top: 5px; }}
                .footer {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd; color: #666; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>Exotel Call Analytics Report</h1>
                <p>Generated on {datetime.now().strftime('%B %d, %Y at %I:%M %p')}</p>
            </div>

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

            <div class="footer">
                <p>This is an automated report from your Exotel Analytics Dashboard.</p>
                <p>For detailed analytics, please visit your dashboard.</p>
            </div>
        </body>
        </html>
        """

        msg.attach(MIMEText(html, 'html'))

        # Send email using Zoho Mail SMTP
        # Try STARTTLS (port 587) first, then SSL (port 465) as fallback
        try:
            # Method 1: Try STARTTLS on port 587
            server = smtplib.SMTP('smtp.zoho.com', 587)
            server.starttls()
            server.login(sender, password)
            server.send_message(msg)
            server.quit()
            logger.info(f"Email report sent successfully to {recipient} via STARTTLS")
            return True
        except Exception as e:
            logger.warning(f"STARTTLS failed: {str(e)}, trying SSL...")
            # Method 2: Fallback to SSL on port 465
            with smtplib.SMTP_SSL('smtp.zoho.com', 465) as server:
                server.login(sender, password)
                server.send_message(msg)
            logger.info(f"Email report sent successfully to {recipient} via SSL")
            return True

    except Exception as e:
        logger.error(f"Error sending email: {str(e)}")
        return False


def send_email_via_infobip(analytics, png_data, start_date, end_date):
    """Send analytics report via Infobip Email API with PNG attachment"""
    try:
        api_key = config['infobip_api_key']
        base_url = config['infobip_base_url']
        from_email = config['infobip_from_email']
        from_name = config['infobip_from_name']
        recipient = config['recipient_email']

        if not all([api_key, base_url, from_email, recipient]):
            logger.error("Infobip configuration incomplete")
            return False

        # Prepare the email content
        subject = f"Exotel Analytics Report - {start_date} to {end_date}"

        # HTML email body
        html_content = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; text-align: center; border-radius: 10px; }}
                .metrics {{ display: flex; flex-wrap: wrap; margin: 20px 0; }}
                .metric-card {{
                    border: 1px solid #ddd;
                    border-radius: 8px;
                    padding: 20px;
                    margin: 10px;
                    min-width: 200px;
                    background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }}
                .metric-value {{ font-size: 36px; font-weight: bold; color: #667eea; }}
                .metric-label {{ font-size: 14px; color: #666; margin-top: 8px; }}
                .footer {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd; color: #666; text-align: center; }}
                .attachment-note {{
                    background-color: #fff3cd;
                    border: 1px solid #ffc107;
                    padding: 15px;
                    border-radius: 5px;
                    margin: 20px 0;
                    text-align: center;
                }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>📊 Exotel Call Analytics Report</h1>
                <p>Generated on {datetime.now().strftime('%B %d, %Y at %I:%M %p')}</p>
                <p>Report Period: {start_date} to {end_date}</p>
            </div>

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

            <div class="attachment-note">
                <strong>📎 Complete Dashboard Report Attached</strong><br>
                Please see the attached PNG file for the complete visual dashboard report.
            </div>

            <div class="footer">
                <p>This is an automated report from your Exotel Analytics Dashboard.</p>
                <p>© {datetime.now().year} Exotel Analytics Dashboard</p>
            </div>
        </body>
        </html>
        """

        # Prepare multipart form data (matching reference implementation)
        url = f"{base_url}/email/3/send"

        # Prepare form data
        data = {
            "from": f"{from_name} <{from_email}>",
            "to": recipient,
            "subject": subject,
            "html": html_content,
        }

        # Prepare file attachment for multipart/form-data
        filename = f"Exotel_Analytics_Report_{start_date}_to_{end_date}.png"
        files = {
            'attachment': (filename, png_data, 'image/png')
        }

        # Prepare headers (matching reference implementation)
        headers = {
            "Authorization": api_key if api_key.startswith("App ") else f"App {api_key}",
        }

        logger.info(f"[INFOBIP-HTTP] Sending POST to {url}")
        logger.info(f"[INFOBIP-HTTP] To: {recipient}, From: {from_email}")

        # Send request using multipart/form-data (matching reference implementation)
        response = requests.post(url, headers=headers, data=data, files=files, timeout=30)

        logger.info(f"[INFOBIP-HTTP] Response status: {response.status_code}")
        logger.info(f"[INFOBIP-HTTP] Response text: {response.text[:500]}")

        if 200 <= response.status_code < 300:
            logger.info(f"Email sent successfully via Infobip to {recipient}")
            return True
        else:
            logger.error(f"Infobip API error: {response.status_code} - {response.text}")
            return False

    except Exception as e:
        logger.error(f"Error sending email via Infobip: {str(e)}")
        return False


def send_scheduled_email_via_infobip(analytics, start_date, end_date):
    """Send scheduled analytics report via Infobip (HTML only, no PNG)"""
    try:
        api_key = config['infobip_api_key']
        base_url = config['infobip_base_url']
        from_email = config['infobip_from_email']
        from_name = config['infobip_from_name']
        recipient = config['recipient_email']

        if not all([api_key, base_url, from_email, recipient]):
            logger.error("Infobip configuration incomplete")
            return False

        # Prepare the email content
        subject = f"📊 Daily Exotel Analytics Report - {start_date}"

        # HTML email body
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
                </div>

                <div class="footer">
                    <p><strong>Automated Daily Report</strong></p>
                    <p>This report is automatically generated every day at 9:30 AM IST</p>
                    <p>Generated on {datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%B %d, %Y at %I:%M %p IST')}</p>
                    <p style="margin-top: 15px;">For detailed analytics, please visit your dashboard</p>
                </div>
            </div>
        </body>
        </html>
        """

        # Prepare multipart form data
        url = f"{base_url}/email/3/send"

        # Prepare form data
        data = {
            "from": f"{from_name} <{from_email}>",
            "to": recipient,
            "subject": subject,
            "html": html_content,
        }

        # Prepare headers
        headers = {
            "Authorization": api_key if api_key.startswith("App ") else f"App {api_key}",
        }

        logger.info(f"[SCHEDULED-INFOBIP] Sending scheduled report to {recipient}")

        # Send request (no attachment for scheduled report)
        # Use dummy files to force multipart/form-data
        dummy_files = {'dummy': ('', '')}
        response = requests.post(url, headers=headers, data=data, files=dummy_files, timeout=30)

        logger.info(f"[SCHEDULED-INFOBIP] Response status: {response.status_code}")

        if 200 <= response.status_code < 300:
            logger.info(f"Scheduled email sent successfully via Infobip to {recipient}")
            return True
        else:
            logger.error(f"Infobip API error: {response.status_code} - {response.text}")
            return False

    except Exception as e:
        logger.error(f"Error sending scheduled email via Infobip: {str(e)}")
        return False


def generate_and_send_report():
    """Generate analytics and send report - used by scheduler"""
    try:
        # Use Indian timezone
        ist = pytz.timezone('Asia/Kolkata')
        now_ist = datetime.now(ist)

        logger.info(f"Starting scheduled report generation at {now_ist.strftime('%Y-%m-%d %I:%M %p IST')}")

        # Get yesterday's data
        yesterday = now_ist - timedelta(days=1)
        start_date = yesterday.strftime('%Y-%m-%d')
        end_date = yesterday.strftime('%Y-%m-%d')

        logger.info(f"Fetching report for date: {start_date}")

        # Fetch and process data
        exotel = ExotelAnalytics(
            config['exotel_api_key'],
            config['exotel_api_token'],
            config['exotel_sid'],
            config['exotel_account_sid']
        )

        calls = exotel.fetch_calls(start_date, end_date)
        exophone_filter = config.get('exophone_number')
        analytics = exotel.process_analytics(calls, exophone_filter=exophone_filter)

        if analytics:
            # Send via Infobip (HTML only for scheduled reports)
            success = send_scheduled_email_via_infobip(analytics, start_date, end_date)
            if success:
                logger.info("Scheduled report sent successfully")
            else:
                logger.error("Failed to send scheduled report")
        else:
            logger.warning("No analytics data available for scheduled report")

    except Exception as e:
        logger.error(f"Error in scheduled report: {str(e)}")


# API Routes
@app.route('/')
def index():
    """Render main dashboard"""
    return render_template('index.html')


@app.route('/api/config', methods=['GET', 'POST'])
def handle_config():
    """Get or update configuration"""
    if request.method == 'POST':
        data = request.json
        config.update(data)
        logger.info("Configuration updated")
        return jsonify({'success': True, 'message': 'Configuration updated'})
    else:
        # Return config without sensitive data
        safe_config = {k: v for k, v in config.items() if 'password' not in k and 'token' not in k}
        return jsonify(safe_config)


@app.route('/api/analytics', methods=['POST'])
def get_analytics():
    """Fetch and return analytics data"""
    try:
        data = request.json
        start_date = data.get('start_date')
        end_date = data.get('end_date')

        if not start_date or not end_date:
            return jsonify({'error': 'Start date and end date required'}), 400

        # Create ExotelAnalytics instance
        exotel = ExotelAnalytics(
            config['exotel_api_key'],
            config['exotel_api_token'],
            config['exotel_sid'],
            config['exotel_account_sid']
        )

        # Fetch calls
        calls = exotel.fetch_calls(start_date, end_date)

        if not calls:
            return jsonify({'error': 'No data available for the selected date range'}), 404

        # Process analytics with exophone filter
        exophone_filter = config.get('exophone_number')
        analytics = exotel.process_analytics(calls, exophone_filter=exophone_filter)

        if not analytics:
            return jsonify({'error': 'Failed to process analytics'}), 500

        # Generate charts
        charts = generate_charts(analytics)

        return jsonify({
            'success': True,
            'analytics': analytics,
            'charts': charts
        })

    except Exception as e:
        logger.error(f"Error in get_analytics: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/send-report', methods=['POST'])
def send_report():
    """Manually trigger report sending"""
    try:
        data = request.json
        analytics = data.get('analytics')
        charts = data.get('charts', {})

        if not analytics:
            return jsonify({'error': 'Analytics data required'}), 400

        success = send_email_report(analytics, charts)

        if success:
            return jsonify({'success': True, 'message': 'Report sent successfully'})
        else:
            return jsonify({'error': 'Failed to send report'}), 500

    except Exception as e:
        logger.error(f"Error sending report: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/schedule', methods=['POST'])
def set_schedule():
    """Set report schedule"""
    try:
        data = request.json
        report_time = data.get('time')  # Expected format: "HH:MM"

        if not report_time:
            return jsonify({'error': 'Time required'}), 400

        # Parse time
        hour, minute = map(int, report_time.split(':'))

        # Remove existing jobs
        scheduler.remove_all_jobs()

        # Use Indian Standard Time (IST) timezone
        ist = pytz.timezone('Asia/Kolkata')

        # Add new job with IST timezone
        scheduler.add_job(
            func=generate_and_send_report,
            trigger=CronTrigger(hour=hour, minute=minute, timezone=ist),
            id='daily_report'
        )

        config['report_time'] = report_time
        logger.info(f"Report scheduled for {report_time} IST daily")

        return jsonify({
            'success': True,
            'message': f'Report scheduled for {report_time} IST daily'
        })

    except Exception as e:
        logger.error(f"Error setting schedule: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/test-email', methods=['POST'])
def test_email():
    """Test email configuration"""
    try:
        test_analytics = {
            'total_calls': 100,
            'incoming_calls': 60,
            'outgoing_calls': 40,
            'answered_calls': 85,
            'missed_calls': 15,
            'avg_duration': 120
        }

        success = send_email_report(test_analytics, {})

        if success:
            return jsonify({'success': True, 'message': 'Test email sent successfully'})
        else:
            return jsonify({'error': 'Failed to send test email'}), 500

    except Exception as e:
        logger.error(f"Error in test email: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/send-email-infobip', methods=['POST'])
def send_email_infobip():
    """Send analytics report via Infobip with PNG attachment"""
    try:
        data = request.json
        analytics = data.get('analytics')
        png_base64 = data.get('png_data')  # Base64 encoded PNG
        start_date = data.get('start_date')
        end_date = data.get('end_date')

        if not all([analytics, png_base64, start_date, end_date]):
            return jsonify({'error': 'Missing required data'}), 400

        # Decode base64 PNG data
        png_data = base64.b64decode(png_base64.split(',')[1] if ',' in png_base64 else png_base64)

        # Send email via Infobip
        success = send_email_via_infobip(analytics, png_data, start_date, end_date)

        if success:
            return jsonify({'success': True, 'message': 'Report sent successfully via email'})
        else:
            return jsonify({'error': 'Failed to send email via Infobip'}), 500

    except Exception as e:
        logger.error(f"Error in send_email_infobip: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/analytics-comparison', methods=['POST'])
def get_analytics_comparison():
    """Get analytics with week-over-week or month-over-month comparison"""
    try:
        data = request.json
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        comparison_type = data.get('comparison_type', 'week')  # 'week' or 'month'

        if not start_date or not end_date:
            return jsonify({'error': 'Start date and end date required'}), 400

        # Create ExotelAnalytics instance
        exotel = ExotelAnalytics(
            config['exotel_api_key'],
            config['exotel_api_token'],
            config['exotel_sid'],
            config['exotel_account_sid']
        )

        # Get current period analytics
        current_calls = exotel.fetch_calls(start_date, end_date)
        exophone_filter = config.get('exophone_number')
        current_analytics = exotel.process_analytics(current_calls, exophone_filter=exophone_filter)

        if not current_analytics:
            return jsonify({'error': 'No data available for current period'}), 404

        # Calculate previous period dates
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')
        period_days = (end_dt - start_dt).days + 1

        if comparison_type == 'week':
            prev_start = (start_dt - timedelta(days=7)).strftime('%Y-%m-%d')
            prev_end = (end_dt - timedelta(days=7)).strftime('%Y-%m-%d')
            comparison_label = 'Week-over-Week'
        else:  # month
            prev_start = (start_dt - timedelta(days=30)).strftime('%Y-%m-%d')
            prev_end = (end_dt - timedelta(days=30)).strftime('%Y-%m-%d')
            comparison_label = 'Month-over-Month'

        # Get previous period analytics
        previous_calls = exotel.fetch_calls(prev_start, prev_end)
        previous_analytics = exotel.process_analytics(previous_calls, exophone_filter=exophone_filter)

        # Calculate comparison
        comparison = calculate_comparison(current_analytics, previous_analytics)

        return jsonify({
            'success': True,
            'current_period': {
                'start_date': start_date,
                'end_date': end_date,
                'analytics': current_analytics
            },
            'previous_period': {
                'start_date': prev_start,
                'end_date': prev_end,
                'analytics': previous_analytics
            },
            'comparison': comparison,
            'comparison_type': comparison_label
        })

    except Exception as e:
        logger.error(f"Error in get_analytics_comparison: {str(e)}")
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    logger.info("Starting Exotel Analytics Dashboard")
    app.run(debug=True, host='0.0.0.0', port=5000)
