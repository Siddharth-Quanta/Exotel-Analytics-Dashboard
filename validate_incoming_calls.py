#!/usr/bin/env python3
"""
Validate Incoming Calls from Exotel API
Analyzes unique callers for specified dates
"""

import requests
from datetime import datetime, timedelta
import os
import csv
import argparse
from dotenv import load_dotenv
from tenant_lookup import get_tenant_lookup

load_dotenv()

api_key = os.getenv('EXOTEL_API_KEY')
api_token = os.getenv('EXOTEL_API_TOKEN')
account_sid = os.getenv('EXOTEL_ACCOUNT_SID')

url = f'https://api.exotel.com/v1/Accounts/{account_sid}/Calls.json'

# ============================================================================
# CONFIGURE DATES - Command-line arguments or defaults
# ============================================================================

def parse_arguments():
    """Parse command-line arguments for custom date ranges"""
    parser = argparse.ArgumentParser(
        description='Validate Incoming Calls from Exotel API',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Last 7 days (default)
  python validate_incoming_calls.py

  # Custom date range
  python validate_incoming_calls.py --start-date 2025-10-16 --end-date 2025-10-22

  # Single date
  python validate_incoming_calls.py --start-date 2025-10-22 --end-date 2025-10-22

  # Last N days
  python validate_incoming_calls.py --last-days 14
        '''
    )

    parser.add_argument(
        '--start-date',
        type=str,
        help='Start date in YYYY-MM-DD format (e.g., 2025-10-16)'
    )

    parser.add_argument(
        '--end-date',
        type=str,
        help='End date in YYYY-MM-DD format (e.g., 2025-10-22)'
    )

    parser.add_argument(
        '--last-days',
        type=int,
        help='Fetch last N days including today (e.g., 7 for last 7 days)'
    )

    return parser.parse_args()

def generate_date_range(args):
    """Generate list of dates based on command-line arguments"""

    # Option 1: Use --last-days
    if args.last_days:
        return [(datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
                for i in range(args.last_days - 1, -1, -1)]

    # Option 2: Use --start-date and --end-date
    if args.start_date and args.end_date:
        try:
            start = datetime.strptime(args.start_date, '%Y-%m-%d')
            end = datetime.strptime(args.end_date, '%Y-%m-%d')

            if start > end:
                print('Error: start-date must be before or equal to end-date')
                exit(1)

            days_diff = (end - start).days + 1
            return [(start + timedelta(days=i)).strftime('%Y-%m-%d')
                    for i in range(days_diff)]
        except ValueError as e:
            print(f'Error parsing dates: {e}')
            print('Please use format YYYY-MM-DD (e.g., 2025-10-16)')
            exit(1)

    # Option 3: Only start-date provided (single day)
    if args.start_date:
        try:
            datetime.strptime(args.start_date, '%Y-%m-%d')
            return [args.start_date]
        except ValueError as e:
            print(f'Error parsing date: {e}')
            print('Please use format YYYY-MM-DD (e.g., 2025-10-16)')
            exit(1)

    # Default: Last 7 days
    print('No date range specified. Using default: Last 7 days')
    return [(datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
            for i in range(6, -1, -1)]

# Parse arguments and generate date range
args = parse_arguments()
dates_to_fetch = generate_date_range(args)

# ============================================================================

print('=' * 80)
print(f'VALIDATING EXOTEL INCOMING CALLS: {", ".join(dates_to_fetch)}')
print('Virtual Number: 08047361499')
print('=' * 80)

all_incoming_calls = []

for date in dates_to_fetch:
    start_time = f'{date} 00:00:00'
    end_time = f'{date} 23:59:59'
    date_filter = f'gte:{start_time};lte:{end_time}'

    print(f'\nFetching calls for {date}...')

    page = 0
    day_calls = []
    next_page_uri = None

    while True:
        # Use NextPageUri for cursor-based pagination (Exotel doesn't use Page numbers)
        if next_page_uri:
            fetch_url = f'https://api.exotel.com{next_page_uri}'
            print(f'  Fetching page {page}...', end=' ', flush=True)
            response = requests.get(fetch_url, auth=(api_key, api_token), timeout=30)
        else:
            params = {
                'DateCreated': date_filter,
                'PageSize': 100
            }
            print(f'  Fetching page {page}...', end=' ', flush=True)
            response = requests.get(url, auth=(api_key, api_token), params=params, timeout=30)

        if response.status_code == 200:
            data = response.json()
            calls = data.get('Calls', [])
            metadata = data.get('Metadata', {})

            if not calls:
                print('No more calls')
                break

            day_calls.extend(calls)
            total = metadata.get('Total', 'Unknown')
            print(f'{len(calls)} calls (Total: {total})')

            # Get next page URI for cursor-based pagination
            next_page_uri = metadata.get('NextPageUri')

            page += 1

            if not next_page_uri:
                print('  Last page reached')
                break
        else:
            print(f'ERROR {response.status_code}')
            break

    # Filter for incoming calls TO virtual number 08047361499 only
    incoming = [c for c in day_calls if c.get('Direction') == 'inbound' and
                ('8047361499' in c.get('To', '') or '8047361499' in c.get('PhoneNumber', ''))]
    all_incoming_calls.extend(incoming)
    print(f'  ✅ Total for {date}: {len(day_calls)} calls, {len(incoming)} incoming to 08047361499')

print('\n' + '=' * 80)
print('INCOMING CALLS SUMMARY (to 08047361499 only)')
print('=' * 80)
print(f'Total INCOMING calls: {len(all_incoming_calls)}')

# Extract unique phone numbers
phone_numbers = {}
for call in all_incoming_calls:
    phone = call.get('From', '')
    if phone:
        if phone not in phone_numbers:
            phone_numbers[phone] = {'count': 0, 'calls': []}
        phone_numbers[phone]['count'] += 1
        phone_numbers[phone]['calls'].append({
            'time': call.get('StartTime', ''),
            'status': call.get('Status', ''),
            'duration': call.get('Duration', 0)
        })

print(f'Unique phone numbers: {len(phone_numbers)}')

# Now check against tenant database
print('\n' + '=' * 80)
print('CHECKING AGAINST TENANT DATABASE')
print('=' * 80)

lookup = get_tenant_lookup()
print(f'Database stats: {lookup.get_stats()}')

print('\nCategorizing phone numbers...')
phone_list = list(phone_numbers.keys())
lookup_results = lookup.batch_lookup(phone_list)

service_calls = 0
enquiry_calls = 0

for phone, (is_tenant, call_type, info) in lookup_results.items():
    if is_tenant and call_type == 'service':
        service_calls += phone_numbers[phone]['count']
    else:
        enquiry_calls += phone_numbers[phone]['count']

print(f'\n✅ Service Calls: {service_calls} ({service_calls/len(all_incoming_calls)*100:.1f}%)')
print(f'✅ Enquiry Calls: {enquiry_calls} ({enquiry_calls/len(all_incoming_calls)*100:.1f}%)')

# Show top callers by category
print('\n' + '=' * 80)
print('TOP 10 SERVICE CALLERS (Existing Tenants):')
print('=' * 80)
print(f'{"Phone":<20} {"Calls":<8} {"Name":<30} {"Property"}')
print('-' * 90)

service_phones = [(phone, info, lookup_results[phone]) for phone, info in phone_numbers.items()
                  if lookup_results[phone][0] and lookup_results[phone][1] == 'service']
service_phones.sort(key=lambda x: x[1]['count'], reverse=True)

for phone, call_info, (is_tenant, call_type, tenant_info) in service_phones[:10]:
    name = (tenant_info.get('name') or 'N/A') if tenant_info else 'N/A'
    prop = (tenant_info.get('property') or 'N/A') if tenant_info else 'N/A'
    print(f'{phone:<20} {call_info["count"]:<8} {name:<30} {prop}')

print('\n' + '=' * 80)
print('TOP 10 ENQUIRY CALLERS (New Prospects):')
print('=' * 80)
print(f'{"Phone":<20} {"Calls":<8} {"First Call":<22} {"Last Call"}')
print('-' * 90)

enquiry_phones = [(phone, info) for phone, info in phone_numbers.items()
                  if not lookup_results[phone][0] or lookup_results[phone][1] == 'enquiry']
enquiry_phones.sort(key=lambda x: x[1]['count'], reverse=True)

for phone, call_info in enquiry_phones[:10]:
    first_call = call_info['calls'][0]['time']
    last_call = call_info['calls'][-1]['time']
    print(f'{phone:<20} {call_info["count"]:<8} {first_call:<22} {last_call}')

print('\n' + '=' * 80)
print('UNIQUE PHONE NUMBERS BY DATE')
print('=' * 80)

# Show unique numbers per date
for date in dates_to_fetch:
    date_calls = [c for c in all_incoming_calls if date in c.get('StartTime', '')]
    unique_phones_on_date = set(c.get('From', '') for c in date_calls if c.get('From'))

    print(f'\n{date}:')
    print(f'  Total Calls: {len(date_calls)}')
    print(f'  Unique Phone Numbers: {len(unique_phones_on_date)}')

print('\n' + '=' * 80)
print('ALL UNIQUE CALLERS (Sorted by Call Count)')
print('=' * 80)
print(f'{"Phone Number":<20} {"Calls":<8} {"Type":<10} {"First Call":<22} {"Last Call"}')
print('-' * 100)

# Sort all unique numbers by first call date (earliest to latest)
sorted_phones = sorted(phone_numbers.items(), key=lambda x: x[1]['calls'][0]['time'])

# Determine which are service vs enquiry
service_phones_set = set(phone for phone, info in phone_numbers.items()
                        if lookup_results.get(phone, (False, 'enquiry', None))[0]
                        and lookup_results.get(phone, (False, 'enquiry', None))[1] == 'service')

# Prepare CSV data
csv_data = []
for phone, call_info in sorted_phones:
    call_type = 'SERVICE' if phone in service_phones_set else 'ENQUIRY'
    type_color = '\033[92m' if call_type == 'SERVICE' else '\033[93m'  # Green/Yellow
    reset = '\033[0m'

    first_call = call_info['calls'][0]['time']
    last_call = call_info['calls'][-1]['time']

    print(f'{phone:<20} {call_info["count"]:<8} {type_color}{call_type:<10}{reset} {first_call:<22} {last_call}')

    # Add to CSV data
    csv_data.append({
        'Number': phone,
        'Type': call_type,
        'Received Date': first_call
    })

# Export to CSV
csv_filename = f'unique_callers_{dates_to_fetch[0]}_to_{dates_to_fetch[-1]}.csv'
with open(csv_filename, 'w', newline='', encoding='utf-8') as csvfile:
    fieldnames = ['Number', 'Type', 'Received Date']
    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

    writer.writeheader()
    writer.writerows(csv_data)

print(f'\n✅ CSV exported: {csv_filename} ({len(csv_data)} unique callers)')

# Show repeat callers
print('\n' + '=' * 80)
print('REPEAT CALLERS (Multiple Calls)')
print('=' * 80)

repeat_callers = [(phone, call_data['count']) for phone, call_data in phone_numbers.items() if call_data['count'] > 1]
if repeat_callers:
    repeat_callers.sort(key=lambda x: x[1], reverse=True)
    print(f'Found {len(repeat_callers)} numbers that called multiple times:\n')

    for phone, count in repeat_callers[:20]:  # Top 20
        call_type = 'SERVICE' if phone in service_phones_set else 'ENQUIRY'
        type_color = '\033[92m' if call_type == 'SERVICE' else '\033[93m'
        reset = '\033[0m'
        print(f'  {phone}: {count} calls ({type_color}{call_type}{reset})')
else:
    print('No repeat callers found.')

print('\n' + '=' * 80)
print('VALIDATION COMPLETE')
print('=' * 80)
print(f'Dates Analyzed: {", ".join(dates_to_fetch)}')
print(f'✅ Total incoming calls validated: {len(all_incoming_calls)}')
print(f'✅ Unique phone numbers: {len(phone_numbers)}')
print(f'✅ Service calls: {service_calls} ({service_calls/len(all_incoming_calls)*100:.1f}%)')
print(f'✅ Enquiry calls: {enquiry_calls} ({enquiry_calls/len(all_incoming_calls)*100:.1f}%)')
print(f'✅ Repeat callers: {len(repeat_callers) if repeat_callers else 0}')

lookup.close()
