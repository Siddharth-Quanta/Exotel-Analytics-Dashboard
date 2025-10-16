# Exotel Analytics Dashboard

A comprehensive Flask-based web application that integrates with Exotel's API to track call analytics and send automated daily reports.

## Features

- Real-time call analytics dashboard
- Clean professional UI with key metrics display
- **Download complete dashboard as PNG image**
- **Send reports via email with PNG attachment (Infobip integration)**
- Filter calls by specific exophone number
- Automated daily email reports at scheduled time (9:30 AM by default)
- Manual report generation on-demand
- Easy configuration through web interface
- Secure credential management with environment variables

## Prerequisites

- Python 3.8 or higher
- Exotel account with API access
- **Infobip account for reliable email delivery (Recommended)**
- Gmail account for sending reports (Legacy SMTP option)

## Quick Start

### 1. Install Python

Make sure Python 3.8+ is installed on your system:
```bash
python --version
```

### 2. Clone/Download the Project

Navigate to your project directory:
```bash
cd "Exotel Analytics Dashboard"
```

### 3. Create Virtual Environment

**Windows:**
```bash
python -m venv venv
venv\Scripts\activate
```

**Mac/Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### 4. Install Dependencies

```bash
pip install -r requirements.txt
```

### 5. Configure Environment Variables

Copy the example environment file and edit it:
```bash
cp .env.example .env
```

Edit `.env` file with your credentials:
```env
EXOTEL_API_KEY=your_api_key_here
EXOTEL_API_TOKEN=your_api_token_here
EXOTEL_SID=your_sid_here
EXOTEL_ACCOUNT_SID=your_account_sid_here

SENDER_EMAIL=your-email@gmail.com
SENDER_PASSWORD=your_gmail_app_password
RECIPIENT_EMAIL=lead@company.com

SECRET_KEY=your-secret-key-here
```

### 6. Run the Application

```bash
python app.py
```

The dashboard will be available at: **http://localhost:5000**

## Getting Exotel API Credentials

1. Log in to your Exotel dashboard at https://my.exotel.com
2. Navigate to **Settings** → **API Settings**
3. Copy the following credentials:
   - API Key
   - API Token
   - SID (Exophone SID)
   - Account SID

## Setting Up Gmail App Password

Since Gmail deprecated "less secure apps", you need to use an App Password:

1. Go to https://myaccount.google.com/security
2. Enable **2-Step Verification** (if not already enabled)
3. Go to **App Passwords** section
4. Generate a new app password:
   - Select app: "Mail"
   - Select device: "Other" (name it "Exotel Dashboard")
5. Copy the 16-character password
6. Use this password in the `.env` file as `SENDER_PASSWORD`

## Using the Dashboard

### Configuration Tab

1. Enter your Exotel API credentials
2. Enter your email configuration
3. Click "Save" buttons
4. Use "Test Email" to verify email setup

### Dashboard Tab

1. Select date range (default is yesterday to today)
2. Click "Load Analytics" to fetch call data
3. View metrics and interactive charts
4. Click "Send Report Now" to manually send email report

### Scheduling Tab

1. Set the time for daily automated reports (24-hour format)
2. Click "Set Schedule"
3. Reports will be sent automatically every day at the specified time

## Project Structure

```
exotel-analytics-dashboard/
│
├── app.py                 # Flask backend with API routes
├── requirements.txt       # Python dependencies
├── .env                   # Environment variables (create from .env.example)
├── .env.example          # Environment template
├── .gitignore            # Git ignore file
├── README.md             # This file
├── templates/
│   └── index.html        # Frontend dashboard UI
└── logs/                 # Application logs (auto-created)
```

## API Endpoints

- `GET /` - Main dashboard UI
- `GET/POST /api/config` - Configuration management
- `POST /api/analytics` - Fetch analytics data
- `POST /api/send-report` - Send email report
- `POST /api/schedule` - Set report schedule
- `POST /api/test-email` - Test email configuration

## Analytics Metrics

The dashboard provides the following metrics:

- **Total Calls**: All calls in the selected date range
- **Incoming Calls**: Number of incoming calls
- **Outgoing Calls**: Number of outgoing calls
- **Answered Calls**: Successfully connected calls
- **Missed Calls**: Unanswered calls
- **Average Duration**: Mean call duration in seconds

## Charts Included

1. **Daily Call Volume**: Line chart showing calls per day
2. **Call Direction Distribution**: Pie chart of incoming vs outgoing
3. **Call Status Distribution**: Bar chart of call outcomes
4. **Hourly Distribution**: Bar chart showing calls by hour of day

## Automated Reports

The system automatically:
- Fetches yesterday's call data
- Generates analytics and charts
- Sends beautifully formatted HTML email report
- Runs daily at your configured time (default 9:30 AM)

## Troubleshooting

### Module Not Found Error

Make sure the virtual environment is activated:
```bash
# Windows
venv\Scripts\activate

# Mac/Linux
source venv/bin/activate
```

Then reinstall dependencies:
```bash
pip install -r requirements.txt
```

### Cannot Connect to Exotel API

- Verify API credentials are correct
- Check your internet connection
- Ensure your IP is not blocked by Exotel
- Test API manually using curl

### Email Not Sending

- Verify you're using Gmail App Password (not regular password)
- Ensure 2-Step Verification is enabled on your Gmail account
- Check that sender email and password are correct
- Look at app.log for detailed error messages

### Port 5000 Already in Use

Change the port in `app.py`:
```python
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)
```

## Logs

Application logs are stored in `app.log` in the project root directory. Check this file for debugging information.

## Security Best Practices

1. **Never commit .env file** - It's already in .gitignore
2. **Use strong SECRET_KEY** - Generate with: `python -c "import secrets; print(secrets.token_hex(32))"`
3. **Keep dependencies updated** - Run: `pip install --upgrade -r requirements.txt`
4. **Use HTTPS in production** - Configure SSL certificate
5. **Restrict API access** - Use IP whitelisting if available

## Production Deployment

### Option 1: Linux Server with Systemd

Create `/etc/systemd/system/exotel-dashboard.service`:
```ini
[Unit]
Description=Exotel Analytics Dashboard
After=network.target

[Service]
Type=simple
User=your-username
WorkingDirectory=/path/to/exotel-analytics-dashboard
Environment="PATH=/path/to/exotel-analytics-dashboard/venv/bin"
ExecStart=/path/to/exotel-analytics-dashboard/venv/bin/python app.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable exotel-dashboard
sudo systemctl start exotel-dashboard
```

### Option 2: Docker

Build and run:
```bash
docker build -t exotel-dashboard .
docker run -d -p 5000:5000 --env-file .env exotel-dashboard
```

### Option 3: Cloud Platforms

Deploy to Heroku, AWS, DigitalOcean, or any cloud platform that supports Python/Flask applications.

## Support

For issues, questions, or contributions:
- Check the logs in `app.log`
- Review Exotel API documentation: https://developer.exotel.com/api/
- Ensure all dependencies are properly installed

## License

This project is provided as-is for use with Exotel services.

## Changelog

### Version 1.0.0
- Initial release
- Real-time analytics dashboard
- Automated email reports
- Configurable scheduling
- Beautiful UI with Plotly charts
