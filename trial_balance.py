"""
Trial Balance Parser

Fetches and parses QuickBooks Online Trial Balance report.
Extracts account balances with proper handling of parent/child accounts.

NOTE: This utility uses the deprecated qbo_client. For production use,
prefer the FastAPI endpoint: GET /api/reports/trial-balance
"""

import json
import re

# Import from deprecated client (will emit DeprecationWarning)
from qbo_client_deprecated import QBOClient


def parse_currency(val):
    """Parse currency string to float"""
    if not val:
        return 0.0
    return float(str(val).replace(',', '').replace('$', '')) or 0.0


def find_account_in_rows(rows, acct_num, depth=0):
    """
    Recursively search for account in Trial Balance rows.

    Args:
        rows: List of row objects from Trial Balance
        acct_num: Account number to find (e.g., '310000')
        depth: Current recursion depth for debugging

    Returns:
        dict with account info or None if not found
    """
    pattern = re.compile(rf'(^|\s){acct_num}(\s|$|\D)')

    for row in rows:
        row_type = row.get('type', '')
        group = row.get('group', '')

        # Check Summary rows (parent account totals)
        if 'Summary' in row and row['Summary'].get('ColData'):
            col_data = row['Summary']['ColData']
            name = col_data[0].get('value', '') if col_data else ''

            if pattern.search(name) or acct_num in name:
                debit = parse_currency(col_data[1].get('value') if len(col_data) > 1 else 0)
                credit = parse_currency(col_data[2].get('value') if len(col_data) > 2 else 0)

                return {
                    'account_num': acct_num,
                    'name': name,
                    'debit': debit,
                    'credit': credit,
                    'balance': debit - credit,
                    'found_in': 'Summary',
                    'depth': depth
                }

        # Check ColData directly on row
        if 'ColData' in row:
            col_data = row['ColData']
            name = col_data[0].get('value', '') if col_data else ''

            if pattern.search(name) or acct_num in name:
                debit = parse_currency(col_data[1].get('value') if len(col_data) > 1 else 0)
                credit = parse_currency(col_data[2].get('value') if len(col_data) > 2 else 0)

                return {
                    'account_num': acct_num,
                    'name': name,
                    'debit': debit,
                    'credit': credit,
                    'balance': debit - credit,
                    'found_in': 'ColData',
                    'depth': depth
                }

        # Check Header rows
        if 'Header' in row and row['Header'].get('ColData'):
            col_data = row['Header']['ColData']
            name = col_data[0].get('value', '') if col_data else ''

            if pattern.search(name) or acct_num in name:
                # Headers typically don't have values, but note we found it
                return {
                    'account_num': acct_num,
                    'name': name,
                    'debit': 0,
                    'credit': 0,
                    'balance': 0,
                    'found_in': 'Header',
                    'depth': depth,
                    'note': 'Found in header - check nested rows for value'
                }

        # Recurse into nested Rows
        if 'Rows' in row and row['Rows'].get('Row'):
            result = find_account_in_rows(row['Rows']['Row'], acct_num, depth + 1)
            if result:
                return result

    return None


def get_account_balance(trial_balance, acct_num):
    """
    Get balance for a specific account number.

    Args:
        trial_balance: Full Trial Balance API response
        acct_num: Account number to find

    Returns:
        float: Account balance (positive = debit, negative = credit)
    """
    rows = trial_balance.get('Rows', {}).get('Row', [])
    result = find_account_in_rows(rows, acct_num)

    if result:
        return result['balance']
    return 0.0


def dump_trial_balance_structure(trial_balance, output_file='trial_balance_structure.json'):
    """Save Trial Balance structure for analysis"""
    with open(output_file, 'w') as f:
        json.dump(trial_balance, f, indent=2)
    print(f"Saved Trial Balance to {output_file}")


def print_account_tree(rows, depth=0, max_depth=3):
    """Print hierarchical view of accounts"""
    indent = "  " * depth

    for row in rows:
        row_type = row.get('type', 'unknown')

        # Get name from various possible locations
        name = None
        if 'Header' in row and row['Header'].get('ColData'):
            name = row['Header']['ColData'][0].get('value', '')
            print(f"{indent}[Header] {name}")

        if 'ColData' in row:
            col_data = row['ColData']
            name = col_data[0].get('value', '') if col_data else ''
            debit = col_data[1].get('value', '') if len(col_data) > 1 else ''
            credit = col_data[2].get('value', '') if len(col_data) > 2 else ''
            print(f"{indent}[Data] {name} | D: {debit} | C: {credit}")

        if 'Summary' in row and row['Summary'].get('ColData'):
            col_data = row['Summary']['ColData']
            name = col_data[0].get('value', '') if col_data else ''
            debit = col_data[1].get('value', '') if len(col_data) > 1 else ''
            credit = col_data[2].get('value', '') if len(col_data) > 2 else ''
            print(f"{indent}[Summary] {name} | D: {debit} | C: {credit}")

        # Recurse
        if depth < max_depth and 'Rows' in row and row['Rows'].get('Row'):
            print_account_tree(row['Rows']['Row'], depth + 1, max_depth)


if __name__ == '__main__':
    import sys

    client = QBOClient()

    if not client.access_token:
        print("No access token. Set QBO_ACCESS_TOKEN in .env")
        sys.exit(1)

    print("Fetching Trial Balance...")
    tb = client.get_trial_balance()

    # Save for analysis
    dump_trial_balance_structure(tb)

    # Test specific accounts
    test_accounts = ['310000', '219500', '100000', '101000', '105001', '105002', '214000', '104000']

    print("\n=== Account Balances ===")
    for acct in test_accounts:
        rows = tb.get('Rows', {}).get('Row', [])
        result = find_account_in_rows(rows, acct)
        if result:
            print(f"{acct}: {result['name']}")
            print(f"  Balance: ${result['balance']:,.2f} (D: ${result['debit']:,.2f}, C: ${result['credit']:,.2f})")
            print(f"  Found in: {result['found_in']} at depth {result['depth']}")
        else:
            print(f"{acct}: NOT FOUND")
        print()

    # Print structure for debugging
    if '--tree' in sys.argv:
        print("\n=== Account Tree ===")
        rows = tb.get('Rows', {}).get('Row', [])
        print_account_tree(rows)
