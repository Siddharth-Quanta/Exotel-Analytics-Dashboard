#!/usr/bin/env python3
"""
Complete Data Validation Script
Checks Exotel API data, phone formats, database matching, and categorization
"""

import requests
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
from tenant_lookup import get_tenant_lookup
import json

load_dotenv()

# Colors for terminal output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
BOLD = '\033[1m'
RESET = '\033[0m'

def print_header(text):
    print(f"\n{BOLD}{BLUE}{'=' * 80}{RESET}")
    print(f"{BOLD}{BLUE}{text.center(80)}{RESET}")
    print(f"{BOLD}{BLUE}{'=' * 80}{RESET}\n")

def print_success(text):
    print(f"{GREEN}✅ {text}{RESET}")

def print_error(text):
    print(f"{RED}❌ {text}{RESET}")

def print_warning(text):
    print(f"{YELLOW}⚠️  {text}{RESET}")

def print_info(text):
    print(f"{BLUE}ℹ️  {text}{RESET}")

def fetch_sample_calls():
    """Fetch a small sample of calls from Exotel API"""
    print_header("STEP 1: FETCH SAMPLE CALLS FROM EXOTEL API")

    api_key = os.getenv('EXOTEL_API_KEY')
    api_token = os.getenv('EXOTEL_API_TOKEN')
    account_sid = os.getenv('EXOTEL_ACCOUNT_SID')

    if not all([api_key, api_token, account_sid]):
        print_error("Missing Exotel credentials in .env")
        return None

    # Get yesterday's calls
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    start_time = f"{yesterday} 00:00:00"
    end_time = f"{yesterday} 23:59:59"
    date_filter = f"gte:{start_time};lte:{end_time}"

    url = f"https://api.exotel.com/v1/Accounts/{account_sid}/Calls.json"
    params = {
        'DateCreated': date_filter,
        'PageSize': 10  # Just get 10 calls for testing
    }

    print_info(f"Fetching calls from: {yesterday}")
    print_info(f"API URL: {url}")

    try:
        response = requests.get(url, auth=(api_key, api_token), params=params, timeout=30)

        if response.status_code == 200:
            data = response.json()
            calls = data.get('Calls', [])
            print_success(f"Fetched {len(calls)} sample calls")
            return calls
        else:
            print_error(f"API request failed: {response.status_code}")
            print_error(f"Response: {response.text[:200]}")
            return None

    except Exception as e:
        print_error(f"Error fetching calls: {e}")
        return None

def analyze_call_structure(calls):
    """Analyze the structure of Exotel call data"""
    print_header("STEP 2: ANALYZE EXOTEL CALL DATA STRUCTURE")

    if not calls:
        print_error("No calls to analyze")
        return

    print_info(f"Analyzing {len(calls)} calls...")

    # Show first call's complete structure
    print(f"\n{BOLD}Sample Call Data (First Call):{RESET}")
    print(json.dumps(calls[0], indent=2)[:1000] + "...")

    # Extract incoming calls
    incoming_calls = [c for c in calls if c.get('Direction') == 'inbound']
    print_success(f"\nFound {len(incoming_calls)} incoming calls out of {len(calls)} total")

    if incoming_calls:
        print(f"\n{BOLD}Phone Number Fields in Incoming Calls:{RESET}")
        sample_call = incoming_calls[0]

        print(f"  From: {sample_call.get('From', 'N/A')}")
        print(f"  To: {sample_call.get('To', 'N/A')}")
        print(f"  PhoneNumber: {sample_call.get('PhoneNumber', 'N/A')}")
        print(f"  Direction: {sample_call.get('Direction', 'N/A')}")
        print(f"  Status: {sample_call.get('Status', 'N/A')}")

        return incoming_calls
    else:
        print_warning("No incoming calls found in sample")
        return []

def test_phone_formats(incoming_calls):
    """Test phone number formats and normalization"""
    print_header("STEP 3: PHONE NUMBER FORMAT ANALYSIS")

    if not incoming_calls:
        print_warning("No incoming calls to analyze")
        return []

    print_info("Extracting phone numbers from 'From' field...")

    phone_numbers = []
    for i, call in enumerate(incoming_calls[:5], 1):  # First 5 calls
        from_number = call.get('From', '')
        phone_numbers.append(from_number)

        print(f"\n{BOLD}Call {i}:{RESET}")
        print(f"  Raw 'From' field: {from_number}")
        print(f"  Length: {len(from_number)}")
        print(f"  Starts with '+': {from_number.startswith('+')}")

        # Show normalization
        normalized = ''.join(filter(str.isdigit, from_number))
        print(f"  After removing non-digits: {normalized}")

        if len(normalized) == 10:
            normalized = '91' + normalized
            print(f"  After adding country code: {normalized}")

    return phone_numbers

def check_database_matches(phone_numbers):
    """Check if phone numbers exist in database"""
    print_header("STEP 4: DATABASE LOOKUP TEST")

    if not phone_numbers:
        print_warning("No phone numbers to check")
        return

    lookup = get_tenant_lookup()

    print_info(f"Checking {len(phone_numbers)} phone numbers against database...")
    print_info(f"Database has: {lookup.get_stats()}")

    matches = 0
    no_matches = 0

    for i, phone in enumerate(phone_numbers, 1):
        print(f"\n{BOLD}Phone {i}: {phone}{RESET}")

        is_tenant, call_type, info = lookup.is_tenant(phone)

        if is_tenant and call_type == 'service':
            matches += 1
            print_success(f"  MATCH FOUND - Service Call")
            print(f"  Tenant Name: {info.get('name', 'N/A')}")
            print(f"  Property: {info.get('property', 'N/A')}")
            print(f"  Found in: {info.get('found_in', 'N/A')}")
        else:
            no_matches += 1
            print_error(f"  NO MATCH - Enquiry Call")

            # Try to find what's in database with similar numbers
            normalized = lookup.normalize_phone(phone)
            print(f"  Normalized to: {normalized}")

    print(f"\n{BOLD}Summary:{RESET}")
    print_success(f"Matches (Service): {matches}/{len(phone_numbers)}")
    print_error(f"No Matches (Enquiry): {no_matches}/{len(phone_numbers)}")

    if no_matches == len(phone_numbers):
        print_warning("\n⚠️  NO MATCHES FOUND! This explains why all calls show as Enquiry.")
        print_info("Possible reasons:")
        print("  1. Phone format mismatch (Exotel uses different format than database)")
        print("  2. These specific numbers are not in your tenant database")
        print("  3. Date mismatch (calls from before database cutoff date)")

def check_sample_database_records():
    """Check what phone formats are actually in the database"""
    print_header("STEP 5: DATABASE PHONE FORMAT CHECK")

    lookup = get_tenant_lookup()

    try:
        conn = lookup._get_connection()
        cursor = conn.cursor()

        # Get 5 sample phone numbers from historical table
        cursor.execute("""
            SELECT phone, mobile, tenant_name, tenant_property_name
            FROM all_tenants_data_upto_2025_09_09
            LIMIT 5;
        """)

        print_info("Sample phone numbers FROM DATABASE:")
        results = cursor.fetchall()

        for i, (phone, mobile, name, property_name) in enumerate(results, 1):
            print(f"\n{BOLD}Database Record {i}:{RESET}")
            print(f"  Name: {name}")
            print(f"  Property: {property_name}")
            print(f"  Phone: {phone}")
            print(f"  Mobile: {mobile}")
            print(f"  Phone Length: {len(phone) if phone else 0}")
            print(f"  Starts with '+': {phone.startswith('+') if phone else False}")

        cursor.close()
        lookup._return_connection(conn)

    except Exception as e:
        print_error(f"Error checking database: {e}")

def main():
    """Run complete validation"""
    print_header("EXOTEL ANALYTICS - COMPLETE DATA VALIDATION")
    print_info("This script will validate:")
    print("  1. Exotel API connection and data format")
    print("  2. Phone number extraction and normalization")
    print("  3. Database lookup matching")
    print("  4. Service vs Enquiry categorization")

    # Step 1: Fetch calls
    calls = fetch_sample_calls()
    if not calls:
        print_error("\nValidation failed: Could not fetch calls from Exotel")
        return

    # Step 2: Analyze structure
    incoming_calls = analyze_call_structure(calls)

    # Step 3: Test phone formats
    phone_numbers = test_phone_formats(incoming_calls)

    # Step 4: Check database matches
    check_database_matches(phone_numbers)

    # Step 5: Check database format
    check_sample_database_records()

    # Final summary
    print_header("VALIDATION COMPLETE")
    print_info("Review the output above to identify any issues.")
    print_info("Common issues:")
    print("  - Phone format mismatch (Exotel: +919876543210, DB: 919876543210)")
    print("  - Missing country code")
    print("  - Spaces or special characters in numbers")
    print_info("\nIf no matches found, the phone formats need to be aligned.")

if __name__ == "__main__":
    main()
