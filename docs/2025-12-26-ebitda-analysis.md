# EBITDA Erosion Analysis & Improvement Strategy

**Date:** December 26, 2025
**Prepared by:** Claude Code (with Burke)

## Executive Summary

Revenue recovered to 2022 levels ($17M), but EBITDA before profit draw dropped from 3.7% to 1.4%. The erosion is almost entirely explained by building out an operations/finance leadership team that didn't exist in 2022.

## Current State

| Metric | 2022 | 2024 | 2025 YTD |
|--------|------|------|----------|
| Revenue | $17.07M | $17.37M | $17.02M |
| Operating Expenses | $1.27M | $1.42M | $1.65M (ann.) |
| EBITDA Before Draw | $628K (3.7%) | $474K (2.7%) | $240K (1.4%) |

## Root Cause: Ops/Finance Leadership Build-Out

| Role | Vendor | 2022 | 2024 | 2025 |
|------|--------|------|------|------|
| Fractional CFO | SeatonHill Partners | $36K | $117K | $171K |
| Fractional COO | Renee Brauns | $0 | $106K | $147K |
| Director of Operations | Katie Buttry | $0 | $41K | $72K |
| Remote Ops (Philippines) | Magic For Business | $0 | $6K | $16K |
| **TOTAL** | | **$36K** | **$270K** | **$406K** |

**+$370K in 3 years = This IS the EBITDA erosion**

## 2026 Automatic Savings

Two one-time/eliminated expenses that won't recur:

| Vendor | 2025 Cost | Status |
|--------|-----------|--------|
| Beyond Measure LLC | $100K | One-time PartnerConnect/Snowflake project |
| Heard Events Inc. | $48K | Partner conference - fired |
| **TOTAL** | **$148K** | **Automatic 2026 savings** |

## Strategy: Two Tracks

### Track 1: SaaS Cleanup ($25-40K savings)

See `saas_audit.csv` for full checklist.

**Recommended Cancellations:**
- Atlassian: $21K/year (should be $0 per Burke)
- GETMAGI: $6K/year (redundant with ChatGPT/Claude)
- Monday.com: $700/year (redundant)
- Lumen5: $1K/year (not being used)

**Review for Potential Savings:**
- Google Apps: $20K → $31K (right # of seats?)
- Amazon AWS: $11K → $18K (what's running?)
- GaggleAMP: $3K (anyone using?)
- SEMRush: $3K (needed?)
- Zoom: $2.4K (Google Meet is included)

### Track 2: AI/Automation to Reduce Leadership Costs ($95-159K savings)

Goal: Automate repetitive CFO/COO tasks → Reduce scope/hours → Renegotiate contracts

**Phase 1: Financial Automation (Q1 2026)**
1. Automated expense monitoring (weekly reports)
2. Partner payment calculator
3. Monthly financial dashboard
4. Cash flow forecasting

**Phase 2: Operations Automation (Q2 2026)**
5. Vendor/contract management
6. Partner onboarding automation
7. Operational metrics dashboard
8. SaaS spend monitoring

**Phase 3: AI-Assisted Analysis (Q3 2026)**
9. Claude Code financial analyst (already started!)
10. Automated anomaly detection

## Projected 2026 Outcomes

| Scenario | OpEx | EBITDA | % of Revenue |
|----------|------|--------|--------------|
| 2025 Current | $1.65M | $240K | 1.4% |
| 2026 Baseline (auto savings only) | $1.50M | $388K | 2.3% |
| 2026 Optimized (SaaS + leadership reduction) | $1.35M | $528K | 3.1% |
| Target (3.5%) | $1.28M | $595K | 3.5% |

## Files Generated

- `pnl_2022.json`, `pnl_2023.json`, `pnl_2024.json` - P&L data by year
- `vendor_analysis.json` - All vendor expense data
- `opex_analysis.json` - Operating expense breakdown
- `saas_audit.csv` - SaaS audit checklist with recommendations

## Next Steps

1. **This week:** Review `saas_audit.csv`, make cancel decisions
2. **Next sprint:** Build automated weekly expense report
3. **January:** Partner payment calculator automation
4. **Q1 2026:** Monthly financial dashboard
