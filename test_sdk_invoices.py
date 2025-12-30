"""Quick test script to fetch 2025 invoices using python-quickbooks SDK."""

import os
from datetime import datetime
from dotenv import load_dotenv
from intuitlib.client import AuthClient
from quickbooks import QuickBooks
from quickbooks.objects.invoice import Invoice

load_dotenv()

# Get credentials from env
client_id = os.getenv('QBO_CLIENT_ID')
client_secret = os.getenv('QBO_CLIENT_SECRET')
access_token = os.getenv('QBO_ACCESS_TOKEN')
refresh_token = os.getenv('QBO_REFRESH_TOKEN')
company_id = os.getenv('QBO_COMPANY_ID', '1208415120')

print(f"Company ID: {company_id}")

# Initialize auth client
auth_client = AuthClient(
    client_id=client_id,
    client_secret=client_secret,
    access_token=access_token,
    refresh_token=refresh_token,
    environment='production',
    redirect_uri='https://developer.intuit.com/v2/OAuth2Playground/RedirectUrl',
)

# Initialize QuickBooks client
client = QuickBooks(
    auth_client=auth_client,
    refresh_token=refresh_token,
    company_id=company_id,
    minorversion=69,
)

print("\nFetching ALL 2025 invoices (with pagination)...")

# Query invoices for 2025 with pagination
start_date = "2025-01-01"
end_date = "2025-12-31"

all_invoices = []
start_position = 1
batch_size = 1000

while True:
    batch = Invoice.query(
        f"SELECT * FROM Invoice WHERE TxnDate >= '{start_date}' AND TxnDate <= '{end_date}' "
        f"STARTPOSITION {start_position} MAXRESULTS {batch_size}",
        qb=client,
    )

    if not batch:
        break

    all_invoices.extend(batch)
    print(f"  Fetched {len(batch)} invoices (total: {len(all_invoices)})")

    if len(batch) < batch_size:
        break

    start_position += batch_size

print(f"\nTotal invoices found: {len(all_invoices)}\n")

# Calculate totals by month
monthly_totals = {}
grand_total = 0.0

for inv in all_invoices:
    txn_date = inv.TxnDate
    total = float(inv.TotalAmt or 0)
    grand_total += total

    month_key = txn_date[:7] if txn_date else "Unknown"
    if month_key not in monthly_totals:
        monthly_totals[month_key] = {"total": 0.0, "count": 0}
    monthly_totals[month_key]["total"] += total
    monthly_totals[month_key]["count"] += 1

# Print summary
print("=" * 60)
print("2025 INVOICE SUMMARY (COMPLETE)")
print("=" * 60)
print(f"{'Month':<12} {'Count':>8} {'Total':>15}")
print("-" * 60)

for month in sorted(monthly_totals.keys()):
    data = monthly_totals[month]
    print(f"{month:<12} {data['count']:>8} ${data['total']:>14,.2f}")

print("-" * 60)
print(f"{'TOTAL':<12} {len(all_invoices):>8} ${grand_total:>14,.2f}")
print("=" * 60)
