/**
 * Generate HTML Email for Transfer Notifications
 *
 * Creates a professional HTML email body with:
 * - Transfer requirements table
 * - Warnings section (if any)
 * - Quick summary
 * - Metadata footer
 *
 * @version 1.2.0
 * @updated 2025-12-03
 */

const data = $input.first().json;

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

/**
 * Parse formatted currency string to number
 */
function parseNum(str) {
    return parseFloat((str || '0').replace(/,/g, ''));
}

/**
 * Get color based on transfer need
 */
function getTransferColor(amount) {
    return parseNum(amount) > 0 ? '#dc3545' : '#28a745';
}

/**
 * Format transfer text
 */
function getTransferText(amount, label = '') {
    const num = parseNum(amount);
    if (num > 0) return '$' + amount;
    return label || 'Fully Covered';
}

// ============================================================================
// STYLES
// ============================================================================

const styles = {
    body: "font-family: Arial, sans-serif; font-size: 14px; color: #333; margin: 0; padding: 20px; background-color: #f8f9fa;",
    container: "max-width: 1000px; margin: 0 auto; background-color: white; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);",
    header: "background-color: #0057b8; color: white; padding: 20px; border-radius: 8px 8px 0 0;",
    headerTitle: "margin: 0; font-size: 24px;",
    headerSubtitle: "margin: 5px 0 0 0; opacity: 0.9;",
    infoBox: "padding: 20px; border-bottom: 1px solid #e9ecef; background-color: #f8f9fa;",
    infoTitle: "margin: 0 0 10px 0; color: #0057b8;",
    content: "padding: 20px;",
    sectionTitle: "color: #0057b8; margin-top: 0;",
    table: "width: 100%; border-collapse: collapse; border: 1px solid #dee2e6;",
    th: "padding: 12px 8px; text-align: left; border: 1px solid #dee2e6; background-color: #f8f9fa;",
    thRight: "padding: 12px 8px; text-align: right; border: 1px solid #dee2e6; background-color: #f8f9fa;",
    td: "padding: 12px 8px; border: 1px solid #dee2e6;",
    tdRight: "padding: 12px 8px; border: 1px solid #dee2e6; text-align: right;",
    tdBold: "padding: 12px 8px; border: 1px solid #dee2e6; font-weight: bold;",
    gpRow: "background-color: #fff9e6;",
    warningBox: "margin-top: 15px; padding: 15px; background-color: #fff3cd; border: 1px solid #ffc107; border-radius: 6px;",
    warningTitle: "margin: 0 0 10px 0; color: #856404;",
    warningItem: "margin: 5px 0; color: #856404;",
    summaryBox: "margin-top: 15px; padding: 15px; background-color: #f8f9fa; border-radius: 6px;",
    summaryTitle: "margin-top: 0; color: #0057b8;",
    footer: "padding: 15px 20px; background-color: #f8f9fa; border-top: 1px solid #e9ecef;",
    footerText: "margin: 0; font-size: 12px; color: #6c757d; text-align: center;",
    green: "#28a745",
    red: "#dc3545",
    gray: "#6c757d"
};

// ============================================================================
// BUILD HTML SECTIONS
// ============================================================================

const capitalColor = getTransferColor(data.CapitalTransferNeeded);
const capitalText = getTransferText(data.CapitalTransferNeeded, 'Fully Covered');
const withholdingColor = getTransferColor(data.WithholdingTransferNeeded);
const withholdingText = getTransferText(data.WithholdingTransferNeeded, 'Fully Covered');
const gpColor = getTransferColor(data.GPTransferNeeded);
const gpText = getTransferText(data.GPTransferNeeded, '$0.00');

const timestamp = data._meta?.executionTimestamp
    ? new Date(data._meta.executionTimestamp).toLocaleString('en-US', { timeZone: 'America/Chicago' })
    : new Date().toISOString().slice(0, 19).replace('T', ' ');

// Header section
const headerHtml = `
<div style="${styles.header}">
    <h1 style="${styles.headerTitle}">Account Transfers Needed</h1>
    <p style="${styles.headerSubtitle}">Data sourced directly from QuickBooks Online Balance Sheet</p>
</div>
`;

// Info box
const infoBoxHtml = `
<div style="${styles.infoBox}">
    <h3 style="${styles.infoTitle}">Understanding the Columns</h3>
    <div style="font-size: 13px;">
        <div><strong>Liability Balance:</strong> Total amount owed | <strong>Current Coverage:</strong> Funds set aside | <strong>Transfer Needed:</strong> Additional funds needed | <strong>Source Account:</strong> Where to transfer from</div>
    </div>
</div>
`;

// Transfer table
const tableHtml = `
<table style="${styles.table}">
    <thead>
        <tr style="background-color: #f8f9fa;">
            <th style="${styles.th}">Account Type</th>
            <th style="${styles.thRight}">Liability</th>
            <th style="${styles.thRight}">Coverage</th>
            <th style="${styles.thRight}">Transfer Needed</th>
            <th style="${styles.th}">Source</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td style="${styles.tdBold}">Capital</td>
            <td style="${styles.tdRight}">$${data.TotalCapital}</td>
            <td style="${styles.tdRight}; color: ${styles.green};">$${data.InterestBearingCapital}</td>
            <td style="${styles.tdRight}"><span style="color: ${capitalColor}; font-weight: bold;">${capitalText}</span></td>
            <td style="${styles.td}">Chase Operating ($${data.OperatingBalance})</td>
        </tr>
        <tr>
            <td style="${styles.tdBold}">Withholding</td>
            <td style="${styles.tdRight}">$${data.TotalWithholding}</td>
            <td style="${styles.tdRight}; color: ${styles.green};">$${data.InterestBearingWithholding}</td>
            <td style="${styles.tdRight}"><span style="color: ${withholdingColor}; font-weight: bold;">${withholdingText}</span></td>
            <td style="${styles.td}">Chase Operating ($${data.OperatingBalance})</td>
        </tr>
        <tr style="${styles.gpRow}">
            <td style="${styles.tdBold}">GP Distribution</td>
            <td style="${styles.tdRight}">$${data.GPPayableRaw}</td>
            <td style="${styles.tdRight}; color: ${styles.gray};">-</td>
            <td style="${styles.tdRight}"><span style="color: ${gpColor}; font-weight: bold;">${gpText}</span></td>
            <td style="${styles.td}">Chase Operating ($${data.OperatingBalance})</td>
        </tr>
    </tbody>
</table>
`;

// Warnings section (if any)
let warningsHtml = '';
if (data._validation?.hasWarnings && data._validation.warnings.length > 0) {
    const warningItems = data._validation.warnings
        .map(w => `<p style="${styles.warningItem}">${w}</p>`)
        .join('');
    warningsHtml = `
<div style="${styles.warningBox}">
    <h4 style="${styles.warningTitle}">Alerts &amp; Warnings</h4>
    ${warningItems}
</div>
`;
}

// Missing accounts alert (critical)
let missingAccountsHtml = '';
if (data._validation?.missingAccounts && data._validation.missingAccounts.length > 0) {
    const missingItems = data._validation.missingAccounts
        .map(a => `<p style="${styles.warningItem}">Missing account: ${a}</p>`)
        .join('');
    missingAccountsHtml = `
<div style="margin-top: 15px; padding: 15px; background-color: #f8d7da; border: 1px solid #f5c6cb; border-radius: 6px;">
    <h4 style="margin: 0 0 10px 0; color: #721c24;">Critical: Missing Accounts</h4>
    ${missingItems}
    <p style="margin: 10px 0 0 0; color: #721c24; font-size: 13px;">Please verify the QuickBooks chart of accounts has not changed.</p>
</div>
`;
}

// Summary section
const summaryHtml = `
<div style="${styles.summaryBox}">
    <h4 style="${styles.summaryTitle}">Quick Summary</h4>
    <p style="margin: 5px 0;"><strong>Total Transfers Needed:</strong> <span style="color: ${styles.red}; font-weight: bold;">$${data.TotalTransfer}</span></p>
    <p style="margin: 5px 0;"><strong>Operating Account Balance:</strong> <span style="color: ${styles.green}; font-weight: bold;">$${data.OperatingBalance}</span></p>
    ${data.operatingBalanceRaw < data.totalTransferNeeded
        ? `<p style="margin: 5px 0; color: ${styles.red};"><strong>WARNING:</strong> Operating balance insufficient for all transfers!</p>`
        : ''}
</div>
`;

// Footer
const version = data._meta?.workflowVersion || '1.0.0';
const footerHtml = `
<div style="${styles.footer}">
    <p style="${styles.footerText}">
        Sent by Fortium automation on ${timestamp} | Data from QuickBooks Online Balance Sheet | Workflow v${version}
    </p>
</div>
`;

// ============================================================================
// COMPOSE FINAL HTML
// ============================================================================

const htmlBody = `<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Account Transfers Needed</title>
</head>
<body style="${styles.body}">
    <div style="${styles.container}">
        ${headerHtml}
        ${infoBoxHtml}
        <div style="${styles.content}">
            <h2 style="${styles.sectionTitle}">Transfer Requirements</h2>
            ${tableHtml}
            ${missingAccountsHtml}
            ${warningsHtml}
            ${summaryHtml}
        </div>
        ${footerHtml}
    </div>
</body>
</html>`;

// Return with all data plus HTML body
return [{
    json: {
        ...data,
        htmlBody: htmlBody
    }
}];
