/**
 * Extract Account Balances from QuickBooks Balance Sheet
 *
 * Calculates transfer requirements for:
 * - Withholding accounts (tax withholding liability vs coverage)
 * - Capital accounts (partner capital liability vs coverage)
 * - GP Distribution (general partner payable)
 *
 * @version 1.2.0
 * @updated 2025-12-03
 * @author Burke Autrey / Claude Code
 */

// ============================================================================
// CONFIGURATION - Update here if chart of accounts changes
// ============================================================================
const CONFIG = {
    // Workflow metadata
    version: '1.2.0',
    lastUpdated: '2025-12-03',

    // Notification settings
    notificationThreshold: 5000,  // Only notify if total transfer >= this amount
    emailRecipients: 'Burke.Autrey@FortiumPartners.com',
    emailFrom: 'Accounting@FortiumPartners.com',

    // Account mappings - QBO account numbers/patterns
    accounts: {
        // Liabilities
        WITHHOLDING_LIABILITY: {
            pattern: /^Total 219500/,
            description: 'Tax withholding liability (all 219500 sub-accounts)'
        },
        CAPITAL_LIABILITY: {
            pattern: /^Total 311000/,
            description: 'Partner capital liability (excludes 310500 Founder capital per accountant)'
        },
        GP_PAYABLE: {
            pattern: /^214000/,
            description: 'GP distribution payable (positive = LP owes GP, negative = GP owes LP)'
        },

        // Coverage accounts - Withholding
        WITHHOLDING_CHECKING: {
            pattern: /^101000/,
            description: 'Chase Withholding checking account'
        },
        WITHHOLDING_INVESTMENT: {
            pattern: /^105002/,
            description: 'Withholding money market investment'
        },

        // Coverage accounts - Capital
        CAPITAL_CHECKING: {
            pattern: /^100000/,
            description: 'Chase Capital checking account'
        },
        CAPITAL_INVESTMENT: {
            pattern: /^105001/,
            description: 'Capital money market investment'
        },

        // Operating
        OPERATING_CHECKING: {
            pattern: /^104000/,
            description: 'Chase Operating checking account (source for transfers)'
        }
    },

    // Sanity check thresholds
    sanityChecks: {
        maxTransferAmount: 500000,      // Alert if any single transfer > $500k
        minOperatingBalance: 10000,     // Alert if operating balance < $10k
        maxTotalTransfer: 1000000       // Alert if total transfer > $1M
    }
};

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

/**
 * Parse currency string to number
 * Handles formats like "$1,234.56", "1234.56", negative values, etc.
 *
 * @param {string|number} val - Value to parse
 * @returns {number} - Parsed numeric value, 0 if invalid
 */
function parseCurrency(val) {
    if (val === null || val === undefined) return 0;
    if (typeof val === 'number') return val;
    return parseFloat(String(val).replace(/[,$]/g, '')) || 0;
}

/**
 * Format number as currency string
 *
 * @param {number} n - Number to format
 * @returns {string} - Formatted string like "1,234.56"
 */
function formatCurrency(n) {
    return n.toLocaleString('en-US', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    });
}

/**
 * Search recursively through QBO Balance Sheet rows to find an account
 *
 * @param {Array} rows - Balance Sheet Row array from QBO API
 * @param {RegExp} pattern - Regex to match account name
 * @returns {Object|null} - {name: string, value: number} or null if not found
 *
 * Note: Searches Header, ColData, and Summary fields to handle
 * both leaf accounts and parent account totals.
 */
function findAccount(rows, pattern) {
    for (const row of rows) {
        // Check Header (section headers with values)
        if (row.Header?.ColData) {
            const name = row.Header.ColData[0]?.value || '';
            if (pattern.test(name)) {
                return {
                    name: name,
                    value: parseCurrency(row.Header.ColData[1]?.value)
                };
            }
        }

        // Check ColData (leaf account rows)
        if (row.ColData) {
            const name = row.ColData[0]?.value || '';
            if (pattern.test(name)) {
                return {
                    name: name,
                    value: parseCurrency(row.ColData[1]?.value)
                };
            }
        }

        // Check Summary (parent account totals)
        if (row.Summary?.ColData) {
            const name = row.Summary.ColData[0]?.value || '';
            if (pattern.test(name)) {
                return {
                    name: name,
                    value: parseCurrency(row.Summary.ColData[1]?.value)
                };
            }
        }

        // Recurse into nested rows
        if (row.Rows?.Row) {
            const found = findAccount(row.Rows.Row, pattern);
            if (found) return found;
        }
    }
    return null;
}

/**
 * Sum multiple account values
 *
 * @param {Array} rows - Balance Sheet rows
 * @param  {...Object} accountConfigs - Account config objects with pattern property
 * @returns {number} - Sum of all account values
 */
function sumAccounts(rows, ...accountConfigs) {
    return accountConfigs.reduce((sum, config) => {
        const account = findAccount(rows, config.pattern);
        return sum + (account?.value || 0);
    }, 0);
}

// ============================================================================
// MAIN EXTRACTION LOGIC
// ============================================================================

const balanceSheet = $input.first().json;
const rows = balanceSheet.Rows?.Row || [];
const ACCT = CONFIG.accounts;

// Track any validation warnings
const warnings = [];
const missingAccounts = [];

// === VALIDATE BALANCE SHEET STRUCTURE ===
if (!balanceSheet.Rows || !Array.isArray(rows) || rows.length === 0) {
    throw new Error('Invalid Balance Sheet structure: missing or empty Rows array');
}

// === WITHHOLDING CALCULATIONS ===
const withholdingLiabilityAccount = findAccount(rows, ACCT.WITHHOLDING_LIABILITY.pattern);
const withholdingLiability = withholdingLiabilityAccount?.value || 0;

if (!withholdingLiabilityAccount) {
    missingAccounts.push('219500 (Withholding Liability)');
}

const withholdingChecking = findAccount(rows, ACCT.WITHHOLDING_CHECKING.pattern)?.value || 0;
const withholdingInvestment = findAccount(rows, ACCT.WITHHOLDING_INVESTMENT.pattern)?.value || 0;
const totalWithholdingCoverage = withholdingChecking + withholdingInvestment;
const withholdingTransferNeeded = Math.max(0, withholdingLiability - totalWithholdingCoverage);

// === CAPITAL CALCULATIONS ===
const capitalLiabilityAccount = findAccount(rows, ACCT.CAPITAL_LIABILITY.pattern);
const capitalLiability = capitalLiabilityAccount?.value || 0;

if (!capitalLiabilityAccount) {
    missingAccounts.push('311000 (Capital Liability)');
}

const capitalChecking = findAccount(rows, ACCT.CAPITAL_CHECKING.pattern)?.value || 0;
const capitalInvestment = findAccount(rows, ACCT.CAPITAL_INVESTMENT.pattern)?.value || 0;
const totalCapitalCoverage = capitalChecking + capitalInvestment;
const capitalTransferNeeded = Math.max(0, capitalLiability - totalCapitalCoverage);

// === GP DISTRIBUTION ===
// 214000 GP Payable:
//   Positive = LP owes GP → transfer needed from Operating to GP
//   Negative = GP owes LP → no transfer needed (GP is paying down debt to LP)
const gpPayableAccount = findAccount(rows, ACCT.GP_PAYABLE.pattern);
const gpPayableValue = gpPayableAccount?.value || 0;
const gpTransferNeeded = gpPayableValue > 0 ? gpPayableValue : 0;

// === OPERATING BALANCE ===
const operatingAccount = findAccount(rows, ACCT.OPERATING_CHECKING.pattern);
const operatingBalance = operatingAccount?.value || 0;

if (!operatingAccount) {
    missingAccounts.push('104000 (Operating Account)');
}

// === TOTAL TRANSFER NEEDED ===
const totalTransferNeeded = withholdingTransferNeeded + capitalTransferNeeded + gpTransferNeeded;

// === SANITY CHECKS ===
const { sanityChecks } = CONFIG;

if (withholdingTransferNeeded > sanityChecks.maxTransferAmount) {
    warnings.push(`ALERT: Withholding transfer ($${formatCurrency(withholdingTransferNeeded)}) exceeds $${formatCurrency(sanityChecks.maxTransferAmount)}`);
}

if (capitalTransferNeeded > sanityChecks.maxTransferAmount) {
    warnings.push(`ALERT: Capital transfer ($${formatCurrency(capitalTransferNeeded)}) exceeds $${formatCurrency(sanityChecks.maxTransferAmount)}`);
}

if (gpTransferNeeded > sanityChecks.maxTransferAmount) {
    warnings.push(`ALERT: GP transfer ($${formatCurrency(gpTransferNeeded)}) exceeds $${formatCurrency(sanityChecks.maxTransferAmount)}`);
}

if (operatingBalance < sanityChecks.minOperatingBalance) {
    warnings.push(`ALERT: Operating balance ($${formatCurrency(operatingBalance)}) is below minimum $${formatCurrency(sanityChecks.minOperatingBalance)}`);
}

if (totalTransferNeeded > sanityChecks.maxTotalTransfer) {
    warnings.push(`ALERT: Total transfer ($${formatCurrency(totalTransferNeeded)}) exceeds maximum $${formatCurrency(sanityChecks.maxTotalTransfer)}`);
}

if (totalTransferNeeded > operatingBalance) {
    warnings.push(`WARNING: Total transfer needed ($${formatCurrency(totalTransferNeeded)}) exceeds operating balance ($${formatCurrency(operatingBalance)})`);
}

// Check for negative liabilities (unusual - may indicate data issue)
if (withholdingLiability < 0) {
    warnings.push(`INFO: Negative withholding liability ($${formatCurrency(withholdingLiability)}) - verify data`);
}
if (capitalLiability < 0) {
    warnings.push(`INFO: Negative capital liability ($${formatCurrency(capitalLiability)}) - verify data`);
}

// === BUILD OUTPUT ===
const fmt = formatCurrency;
const executionTimestamp = new Date().toISOString();

return [{
    json: {
        // Workflow metadata
        _meta: {
            workflowVersion: CONFIG.version,
            executionTimestamp: executionTimestamp,
            configuredThreshold: CONFIG.notificationThreshold,
            emailRecipients: CONFIG.emailRecipients
        },

        // Validation status
        _validation: {
            isValid: missingAccounts.length === 0,
            missingAccounts: missingAccounts,
            warnings: warnings,
            hasWarnings: warnings.length > 0
        },

        // Withholding
        TotalWithholding: fmt(withholdingLiability),
        InterestBearingWithholding: fmt(totalWithholdingCoverage),
        WithholdingTransferNeeded: fmt(withholdingTransferNeeded),

        // Capital
        TotalCapital: fmt(capitalLiability),
        InterestBearingCapital: fmt(totalCapitalCoverage),
        CapitalTransferNeeded: fmt(capitalTransferNeeded),

        // GP
        GPTransferNeeded: fmt(gpTransferNeeded),
        GPPayableRaw: fmt(gpPayableValue),

        // Total
        TotalTransfer: fmt(totalTransferNeeded),

        // Bank balances
        CapitalBalance: fmt(capitalChecking),
        WithholdingBalance: fmt(withholdingChecking),
        OperatingBalance: fmt(operatingBalance),

        // Numeric values for filtering/logic
        totalTransferNeeded: totalTransferNeeded,
        operatingBalanceRaw: operatingBalance,

        // Detailed debug info
        _debug: {
            withholding: {
                liabilityAccountFound: withholdingLiabilityAccount?.name || 'NOT FOUND',
                liability: withholdingLiability,
                checkingCoverage: withholdingChecking,
                investmentCoverage: withholdingInvestment,
                totalCoverage: totalWithholdingCoverage,
                transferNeeded: withholdingTransferNeeded
            },
            capital: {
                liabilityAccountFound: capitalLiabilityAccount?.name || 'NOT FOUND',
                liability: capitalLiability,
                checkingCoverage: capitalChecking,
                investmentCoverage: capitalInvestment,
                totalCoverage: totalCapitalCoverage,
                transferNeeded: capitalTransferNeeded
            },
            gp: {
                accountFound: gpPayableAccount?.name || 'NOT FOUND',
                rawValue: gpPayableValue,
                interpretation: gpPayableValue > 0 ? 'LP owes GP' : gpPayableValue < 0 ? 'GP owes LP' : 'Settled',
                transferNeeded: gpTransferNeeded
            },
            operating: {
                accountFound: operatingAccount?.name || 'NOT FOUND',
                balance: operatingBalance,
                sufficientForTransfers: operatingBalance >= totalTransferNeeded
            }
        },

        // Configuration reference (for audit trail)
        _config: CONFIG
    }
}];
