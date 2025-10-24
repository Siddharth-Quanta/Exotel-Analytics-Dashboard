"""
Tenant Phone Number Lookup Module
Checks if phone numbers belong to existing tenants (Service Calls) or new prospects (Enquiry Calls)
"""

import psycopg2
from psycopg2 import pool
import os
from dotenv import load_dotenv
import logging
from functools import lru_cache

load_dotenv()

logger = logging.getLogger(__name__)

# Database configuration
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'kots-db-cluster.cluster-ch8uu0w02w3b.ap-south-1.rds.amazonaws.com'),
    'port': int(os.getenv('DB_PORT', 5432)),
    'database': os.getenv('DB_NAME', 'kots_prod'),
    'user': os.getenv('DB_USER', 'postgres'),
    'password': os.getenv('DB_PASSWORD', ')rD*4PW(lrm-)F-F6Z0XWcd~a9_B')
}

# Table names
HISTORICAL_TABLE = 'all_tenants_data_upto_2025_09_09'
LIVE_TABLE = 'flat_booking_orders'
LIVE_TABLE_PHONE_COLUMN = 'tenant_phone_number'


class TenantLookup:
    """Handles tenant phone number lookups across multiple tables"""

    def __init__(self):
        """Initialize database connection pool"""
        try:
            self.connection_pool = psycopg2.pool.SimpleConnectionPool(
                minconn=1,
                maxconn=10,
                **DB_CONFIG
            )
            logger.info("Database connection pool created successfully")
        except Exception as e:
            logger.error(f"Failed to create connection pool: {e}")
            self.connection_pool = None

    def _get_connection(self):
        """Get a connection from the pool"""
        if not self.connection_pool:
            raise Exception("Database connection pool not available")
        return self.connection_pool.getconn()

    def _return_connection(self, conn):
        """Return connection to the pool"""
        if self.connection_pool:
            self.connection_pool.putconn(conn)

    def normalize_phone(self, phone):
        """Normalize phone number for matching"""
        if not phone:
            return None

        # Convert to string and remove all non-digit characters
        phone_str = str(phone)
        normalized = ''.join(filter(str.isdigit, phone_str))

        # Handle different formats:
        # +919876543210 -> 919876543210
        # 919876543210 -> 919876543210
        # 9876543210 -> 919876543210 (add country code)
        # 08840810719 -> 918840810719 (remove leading 0, add country code)

        # Remove leading zero if present (common in Indian landlines/mobiles)
        if normalized.startswith('0') and len(normalized) == 11:
            normalized = normalized[1:]  # Remove leading 0: 08840810719 -> 8840810719

        if len(normalized) == 10:
            # Add country code 91 (India)
            normalized = '91' + normalized
        elif len(normalized) == 12 and normalized.startswith('91'):
            # Already has country code
            pass
        elif len(normalized) > 12:
            # Take last 12 digits
            normalized = normalized[-12:]

        return normalized

    def is_tenant(self, phone_number):
        """
        Check if phone number belongs to an existing tenant
        Returns: (is_tenant: bool, source: str, tenant_info: dict)
        """
        if not phone_number:
            return False, None, None

        normalized_phone = self.normalize_phone(phone_number)
        if not normalized_phone:
            return False, None, None

        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # STEP 1: Check in live table (flat_booking_orders) first
            query_live = f"""
                SELECT {LIVE_TABLE_PHONE_COLUMN}, COUNT(*) as count
                FROM {LIVE_TABLE}
                WHERE REGEXP_REPLACE({LIVE_TABLE_PHONE_COLUMN}, '[^0-9]', '', 'g') = %s
                GROUP BY {LIVE_TABLE_PHONE_COLUMN}
                LIMIT 1;
            """

            cursor.execute(query_live, (normalized_phone,))
            result = cursor.fetchone()

            if result:
                tenant_info = {
                    'phone': result[0],
                    'found_in': 'live_data',
                    'table': LIVE_TABLE
                }
                cursor.close()
                return True, 'service', tenant_info

            # STEP 2: Check in historical table
            query_historical = f"""
                SELECT phone, tenant_name, tenant_property_name, tenant_booking_id
                FROM {HISTORICAL_TABLE}
                WHERE REGEXP_REPLACE(phone, '[^0-9]', '', 'g') = %s
                   OR REGEXP_REPLACE(mobile, '[^0-9]', '', 'g') = %s
                LIMIT 1;
            """

            cursor.execute(query_historical, (normalized_phone, normalized_phone))
            result = cursor.fetchone()

            if result:
                tenant_info = {
                    'phone': result[0],
                    'name': result[1],
                    'property': result[2],
                    'booking_id': result[3],
                    'found_in': 'historical_data',
                    'table': HISTORICAL_TABLE
                }
                cursor.close()
                return True, 'service', tenant_info

            # Not found in either table - it's an enquiry call
            cursor.close()
            return False, 'enquiry', None

        except Exception as e:
            logger.error(f"Error checking tenant status for {phone_number}: {e}")
            return False, 'unknown', None

        finally:
            if conn:
                self._return_connection(conn)

    def batch_lookup(self, phone_numbers):
        """
        Look up multiple phone numbers at once (more efficient)
        Returns: dict {phone: (is_tenant, source, info)}
        """
        results = {}

        if not phone_numbers:
            return results

        # Normalize all phone numbers
        normalized_phones = {self.normalize_phone(p): p for p in phone_numbers if p}

        if not normalized_phones:
            return results

        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            normalized_list = list(normalized_phones.keys())

            # Query live table
            query_live = f"""
                SELECT REGEXP_REPLACE({LIVE_TABLE_PHONE_COLUMN}, '[^0-9]', '', 'g') as normalized_phone
                FROM {LIVE_TABLE}
                WHERE REGEXP_REPLACE({LIVE_TABLE_PHONE_COLUMN}, '[^0-9]', '', 'g') = ANY(%s);
            """

            cursor.execute(query_live, (normalized_list,))
            live_results = {row[0] for row in cursor.fetchall()}

            # Query historical table
            query_historical = f"""
                SELECT REGEXP_REPLACE(phone, '[^0-9]', '', 'g') as normalized_phone,
                       tenant_name, tenant_property_name
                FROM {HISTORICAL_TABLE}
                WHERE REGEXP_REPLACE(phone, '[^0-9]', '', 'g') = ANY(%s)
                   OR REGEXP_REPLACE(mobile, '[^0-9]', '', 'g') = ANY(%s);
            """

            cursor.execute(query_historical, (normalized_list, normalized_list))
            historical_results = {row[0]: {'name': row[1], 'property': row[2]} for row in cursor.fetchall()}

            # Build results
            for normalized, original in normalized_phones.items():
                if normalized in live_results:
                    results[original] = (True, 'service', {'found_in': 'live_data'})
                elif normalized in historical_results:
                    results[original] = (True, 'service', {
                        'found_in': 'historical_data',
                        **historical_results[normalized]
                    })
                else:
                    results[original] = (False, 'enquiry', None)

            cursor.close()

        except Exception as e:
            logger.error(f"Error in batch lookup: {e}")

        finally:
            if conn:
                self._return_connection(conn)

        return results

    def get_stats(self):
        """Get statistics about tenant data"""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            stats = {}

            # Count historical records
            cursor.execute(f"SELECT COUNT(*) FROM {HISTORICAL_TABLE};")
            stats['historical_count'] = cursor.fetchone()[0]

            # Count live records
            cursor.execute(f"SELECT COUNT(*) FROM {LIVE_TABLE};")
            stats['live_count'] = cursor.fetchone()[0]

            stats['total_count'] = stats['historical_count'] + stats['live_count']

            cursor.close()
            return stats

        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return None

        finally:
            if conn:
                self._return_connection(conn)

    def close(self):
        """Close all connections in the pool"""
        if self.connection_pool:
            self.connection_pool.closeall()
            logger.info("Database connection pool closed")


# Global instance
_tenant_lookup = None

def get_tenant_lookup():
    """Get or create the global TenantLookup instance"""
    global _tenant_lookup
    if _tenant_lookup is None:
        _tenant_lookup = TenantLookup()
    return _tenant_lookup


# Convenience functions
def is_service_call(phone_number):
    """
    Quick check if a phone number is a service call (existing tenant)
    Returns: bool
    """
    lookup = get_tenant_lookup()
    is_tenant, call_type, _ = lookup.is_tenant(phone_number)
    return is_tenant and call_type == 'service'


def categorize_call(phone_number):
    """
    Categorize a call as 'service' or 'enquiry'
    Returns: str ('service' or 'enquiry')
    """
    lookup = get_tenant_lookup()
    is_tenant, call_type, _ = lookup.is_tenant(phone_number)
    return call_type if call_type != 'unknown' else 'enquiry'


# Example usage
if __name__ == "__main__":
    # Test the lookup
    print("Testing Tenant Lookup System")
    print("=" * 60)

    lookup = TenantLookup()

    # Test with sample phone numbers from CSV
    test_numbers = [
        '916282685100',  # Karina Krishnakumar Nair
        '919703828993',  # Sunkaranam Akash
        '919999999999',  # Non-existent number (should be enquiry)
        '+919876543210', # Test with + prefix
    ]

    for phone in test_numbers:
        is_tenant, call_type, info = lookup.is_tenant(phone)
        print(f"\nPhone: {phone}")
        print(f"  Is Tenant: {is_tenant}")
        print(f"  Call Type: {call_type}")
        print(f"  Info: {info}")

    # Get stats
    print("\n" + "=" * 60)
    stats = lookup.get_stats()
    if stats:
        print("Database Statistics:")
        print(f"  Historical records: {stats['historical_count']:,}")
        print(f"  Live records: {stats['live_count']:,}")
        print(f"  Total: {stats['total_count']:,}")

    lookup.close()
