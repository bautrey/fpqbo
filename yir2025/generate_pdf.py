#!/usr/bin/env python3
"""
Fortium Partners Year in Review 2025 - PDF Generator
"""

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, white, black
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, Image, KeepTogether
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.pdfgen import canvas
from reportlab.lib import colors
import os

# Brand Colors
NAVY = HexColor('#1a365d')
GOLD = HexColor('#d69e2e')
LIGHT_NAVY = HexColor('#2c5282')
LIGHT_GRAY = HexColor('#f7fafc')
DARK_GRAY = HexColor('#4a5568')

def create_styles():
    """Create custom paragraph styles"""
    styles = getSampleStyleSheet()

    # Cover title
    styles.add(ParagraphStyle(
        name='CoverTitle',
        parent=styles['Title'],
        fontSize=42,
        textColor=NAVY,
        alignment=TA_CENTER,
        spaceAfter=20,
        fontName='Helvetica-Bold'
    ))

    # Cover subtitle
    styles.add(ParagraphStyle(
        name='CoverSubtitle',
        parent=styles['Normal'],
        fontSize=18,
        textColor=DARK_GRAY,
        alignment=TA_CENTER,
        spaceAfter=10
    ))

    # Section header
    styles.add(ParagraphStyle(
        name='SectionHeader',
        parent=styles['Heading1'],
        fontSize=28,
        textColor=NAVY,
        spaceBefore=0,
        spaceAfter=20,
        fontName='Helvetica-Bold'
    ))

    # Subsection header
    styles.add(ParagraphStyle(
        name='SubHeader',
        parent=styles['Heading2'],
        fontSize=16,
        textColor=LIGHT_NAVY,
        spaceBefore=15,
        spaceAfter=10,
        fontName='Helvetica-Bold'
    ))

    # Body text - override existing
    styles['BodyText'].fontSize = 11
    styles['BodyText'].textColor = DARK_GRAY
    styles['BodyText'].spaceBefore = 6
    styles['BodyText'].spaceAfter = 6
    styles['BodyText'].leading = 16

    # Big number
    styles.add(ParagraphStyle(
        name='BigNumber',
        parent=styles['Normal'],
        fontSize=48,
        textColor=NAVY,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold'
    ))

    # Number label
    styles.add(ParagraphStyle(
        name='NumberLabel',
        parent=styles['Normal'],
        fontSize=12,
        textColor=DARK_GRAY,
        alignment=TA_CENTER
    ))

    # Quote
    styles.add(ParagraphStyle(
        name='Quote',
        parent=styles['Normal'],
        fontSize=14,
        textColor=LIGHT_NAVY,
        alignment=TA_CENTER,
        fontName='Helvetica-Oblique',
        spaceBefore=20,
        spaceAfter=20
    ))

    return styles


def create_table_style():
    """Standard table style"""
    return TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), NAVY),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('TOPPADDING', (0, 0), (-1, 0), 10),
        ('BACKGROUND', (0, 1), (-1, -1), white),
        ('TEXTCOLOR', (0, 1), (-1, -1), DARK_GRAY),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, LIGHT_GRAY]),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
        ('TOPPADDING', (0, 1), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
    ])


def add_page_number(canvas, doc):
    """Add page number to each page"""
    page_num = canvas.getPageNumber()
    if page_num > 1:  # Skip cover page
        text = f"{page_num}"
        canvas.saveState()
        canvas.setFont('Helvetica', 9)
        canvas.setFillColor(DARK_GRAY)
        canvas.drawRightString(7.5 * inch, 0.5 * inch, text)
        canvas.restoreState()


def build_cover_page(styles):
    """Build cover page elements"""
    elements = []
    elements.append(Spacer(1, 2.5 * inch))
    elements.append(Paragraph("FORTIUM PARTNERS", styles['CoverTitle']))
    elements.append(Spacer(1, 0.3 * inch))
    elements.append(Paragraph("Year in Review", styles['CoverSubtitle']))
    elements.append(Paragraph("2025", ParagraphStyle(
        'Year', parent=styles['CoverTitle'], fontSize=72, spaceAfter=30
    )))
    elements.append(Spacer(1, 0.5 * inch))
    elements.append(Paragraph("Technology Leadership-as-a-Service Since 2014", styles['CoverSubtitle']))
    elements.append(PageBreak())
    return elements


def build_letter_page(styles):
    """Build leadership letter page"""
    elements = []
    elements.append(Paragraph("Stronger Together", styles['SectionHeader']))
    elements.append(Paragraph("A Year of Growth and Partnership", styles['SubHeader']))
    elements.append(Spacer(1, 0.2 * inch))

    letter_text = """
    2025 marked another milestone year for Fortium Partners. As we reflect on the past twelve months,
    we're proud of what our partner network has accomplished together—helping over 200 companies
    navigate technology challenges, scale operations, and achieve their strategic goals.
    """
    elements.append(Paragraph(letter_text.strip(), styles['BodyText']))

    letter_text2 = """
    Since our founding in 2014, we've built the largest network of operating technology executives
    in the world—CIOs, CTOs, and CISOs—united by a shared commitment to delivering exceptional
    technology leadership. This year, we welcomed 18 new partners to our family, expanded our
    geographic reach, and continued to demonstrate that fractional technology leadership isn't just
    a cost-effective alternative—it's often the superior choice for growing companies.
    """
    elements.append(Paragraph(letter_text2.strip(), styles['BodyText']))

    letter_text3 = """
    Thank you to our partners for their dedication, our clients for their trust, and our team for
    making it all possible.
    """
    elements.append(Paragraph(letter_text3.strip(), styles['BodyText']))

    elements.append(Spacer(1, 0.3 * inch))
    elements.append(Paragraph("<b>Here's to an even stronger 2026.</b>", styles['BodyText']))
    elements.append(PageBreak())
    return elements


def build_numbers_page(styles):
    """Build By the Numbers page"""
    elements = []
    elements.append(Paragraph("By the Numbers", styles['SectionHeader']))

    # Big metrics row
    metrics = [
        ("$17.0M", "Revenue"),
        ("1,566", "Invoices"),
        ("211", "Engagements"),
        ("339", "Partners"),
    ]

    metric_data = []
    for value, label in metrics:
        metric_data.append([
            Paragraph(value, styles['BigNumber']),
            Paragraph(label, styles['NumberLabel'])
        ])

    # Create metrics as individual tables stacked
    for value, label in metrics[:2]:
        elements.append(Spacer(1, 0.2 * inch))
        elements.append(Paragraph(value, styles['BigNumber']))
        elements.append(Paragraph(label, styles['NumberLabel']))

    elements.append(Spacer(1, 0.3 * inch))

    for value, label in metrics[2:]:
        elements.append(Paragraph(value, styles['BigNumber']))
        elements.append(Paragraph(label, styles['NumberLabel']))
        elements.append(Spacer(1, 0.2 * inch))

    elements.append(Spacer(1, 0.3 * inch))
    elements.append(Paragraph("Four-Year Revenue Trend", styles['SubHeader']))

    trend_data = [
        ['Year', 'Invoiced', 'Invoices', 'Engagements'],
        ['2022', '$17.3M', '1,397', '179'],
        ['2023', '$14.9M', '1,261', '164'],
        ['2024', '$17.8M', '1,507', '189'],
        ['2025', '$17.0M', '1,566', '211'],
    ]

    trend_table = Table(trend_data, colWidths=[1.2*inch, 1.5*inch, 1.2*inch, 1.5*inch])
    trend_table.setStyle(create_table_style())
    elements.append(trend_table)

    elements.append(Spacer(1, 0.2 * inch))
    elements.append(Paragraph(
        "<b>Key Insight:</b> While revenue remained consistent, we increased our engagement count by 12%—serving more clients than ever before.",
        styles['BodyText']
    ))

    elements.append(PageBreak())
    return elements


def build_network_page(styles):
    """Build Our Network page"""
    elements = []
    elements.append(Paragraph("Our Partner Network", styles['SectionHeader']))

    elements.append(Paragraph("339", styles['BigNumber']))
    elements.append(Paragraph("Total Partners", styles['NumberLabel']))
    elements.append(Spacer(1, 0.1 * inch))
    elements.append(Paragraph("18", styles['BigNumber']))
    elements.append(Paragraph("New Partners in 2025", styles['NumberLabel']))

    elements.append(Spacer(1, 0.3 * inch))
    elements.append(Paragraph("Welcome to the Team", styles['SubHeader']))

    new_partners = [
        ['Name', 'Location', 'Joined'],
        ['Greg Russell', 'Bainbridge Island, WA', 'January'],
        ['Aman Bhasin', '—', 'January'],
        ['Relle Howard', 'Dallas, TX', 'January'],
        ['Dylan Blankenship', 'Dawsonville, GA', 'February'],
        ['Gregory Pfluger', 'Monona, WI', 'February'],
        ['Frank Schettini', 'Middletown, DE', 'March'],
        ['Maureen Minard', 'Nashville, TN', 'March'],
        ['Markus Weber', 'Mars, PA', 'April'],
        ['Ted Tyree', 'Lansdale, PA', 'May'],
        ['Ian Hill', '—', 'June'],
        ['Michael Payne', 'College Grove, TN', 'June'],
        ['Mike Murdock', 'Westerville, OH', 'July'],
        ['Chris Middleton', 'Alexandria, VA', 'July'],
        ['Sandra Keaveny', 'Lititz, PA', 'July'],
        ['Vicki Lynch', 'Webster, MA', 'September'],
        ['Nachiket Desai', 'Frisco, TX', 'September'],
        ['Dean Clark', 'Chicago, IL', 'September'],
        ['Winston Benedict', 'Ann Arbor, MI', 'October'],
    ]

    partner_table = Table(new_partners, colWidths=[2*inch, 2.2*inch, 1.2*inch])
    partner_table.setStyle(create_table_style())
    elements.append(partner_table)

    elements.append(PageBreak())

    # Page 2 - Geographic distribution
    elements.append(Paragraph("Partners by State", styles['SubHeader']))

    state_data = [
        ['State', 'Partners', '', 'State', 'Partners'],
        ['California', '54', '', 'New York', '10'],
        ['Texas', '42', '', 'New Jersey', '9'],
        ['Illinois', '25', '', 'Colorado', '8'],
        ['Florida', '19', '', 'North Carolina', '8'],
        ['Pennsylvania', '18', '', 'Maryland', '7'],
        ['Michigan', '14', '', 'Arizona', '7'],
        ['Georgia', '14', '', 'Tennessee', '6'],
        ['Virginia', '14', '', '', ''],
    ]

    state_table = Table(state_data, colWidths=[1.3*inch, 0.8*inch, 0.3*inch, 1.3*inch, 0.8*inch])
    state_style = TableStyle([
        ('BACKGROUND', (0, 0), (1, 0), NAVY),
        ('BACKGROUND', (3, 0), (4, 0), NAVY),
        ('TEXTCOLOR', (0, 0), (1, 0), white),
        ('TEXTCOLOR', (3, 0), (4, 0), white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('ALIGN', (4, 0), (4, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (1, -1), 0.5, colors.lightgrey),
        ('GRID', (3, 0), (4, -1), 0.5, colors.lightgrey),
        ('ROWBACKGROUNDS', (0, 1), (1, -1), [white, LIGHT_GRAY]),
        ('ROWBACKGROUNDS', (3, 1), (4, -1), [white, LIGHT_GRAY]),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
    ])
    state_table.setStyle(state_style)
    elements.append(state_table)

    elements.append(PageBreak())
    return elements


def build_clients_page(styles):
    """Build Client Impact page"""
    elements = []
    elements.append(Paragraph("Client Impact", styles['SectionHeader']))

    elements.append(Paragraph("609", styles['BigNumber']))
    elements.append(Paragraph("Total Clients Served", styles['NumberLabel']))
    elements.append(Spacer(1, 0.1 * inch))
    elements.append(Paragraph("61", styles['BigNumber']))
    elements.append(Paragraph("New Clients in 2025", styles['NumberLabel']))

    elements.append(Spacer(1, 0.3 * inch))
    elements.append(Paragraph("Industries We Serve", styles['SubHeader']))

    industry_data = [
        ['Industry', 'Companies'],
        ['Internet Software & Services', '192'],
        ['Professional Services', '162'],
        ['Capital Markets', '75'],
        ['Health Care Providers', '69'],
        ['Insurance', '67'],
        ['Media', '65'],
        ['Construction & Engineering', '60'],
        ['Diversified Financial Services', '40'],
        ['Diversified Consumer Services', '39'],
        ['Real Estate', '38'],
    ]

    industry_table = Table(industry_data, colWidths=[3.5*inch, 1.2*inch])
    industry_table.setStyle(create_table_style())
    elements.append(industry_table)

    elements.append(Spacer(1, 0.3 * inch))
    elements.append(Paragraph("Client Geography (Top 10)", styles['SubHeader']))

    client_geo = [
        ['State', 'Clients', '', 'State', 'Clients'],
        ['Texas', '117', '', 'Georgia', '22'],
        ['California', '99', '', 'Pennsylvania', '22'],
        ['New York', '46', '', 'Virginia', '19'],
        ['Illinois', '37', '', 'Massachusetts', '19'],
        ['Florida', '25', '', 'New Jersey', '18'],
    ]

    geo_table = Table(client_geo, colWidths=[1.3*inch, 0.8*inch, 0.3*inch, 1.3*inch, 0.8*inch])
    geo_style = TableStyle([
        ('BACKGROUND', (0, 0), (1, 0), NAVY),
        ('BACKGROUND', (3, 0), (4, 0), NAVY),
        ('TEXTCOLOR', (0, 0), (1, 0), white),
        ('TEXTCOLOR', (3, 0), (4, 0), white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('ALIGN', (4, 0), (4, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (1, -1), 0.5, colors.lightgrey),
        ('GRID', (3, 0), (4, -1), 0.5, colors.lightgrey),
        ('ROWBACKGROUNDS', (0, 1), (1, -1), [white, LIGHT_GRAY]),
        ('ROWBACKGROUNDS', (3, 1), (4, -1), [white, LIGHT_GRAY]),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
    ])
    geo_table.setStyle(geo_style)
    elements.append(geo_table)

    elements.append(PageBreak())
    return elements


def build_delivery_page(styles):
    """Build How We Deliver page"""
    elements = []
    elements.append(Paragraph("How We Deliver", styles['SectionHeader']))

    elements.append(Paragraph("Engagement Types (2025)", styles['SubHeader']))

    engagement_data = [
        ['Type', 'Count', 'Description'],
        ['Fractional', '88', 'Ongoing part-time technology leadership'],
        ['Assessment', '17', 'IT strategy and operations evaluation'],
        ['Situational', '13', 'Project-based engagement'],
        ['Interim', '10', 'Full-time temporary CIO/CTO/CISO'],
        ['Virtual', '5', 'Remote technology leadership'],
        ['Advisory', '2', 'Strategic guidance'],
        ['Due Diligence', '1', 'Technology M&A assessment'],
    ]

    engagement_table = Table(engagement_data, colWidths=[1.2*inch, 0.8*inch, 3.5*inch])
    engagement_table.setStyle(create_table_style())
    elements.append(engagement_table)

    elements.append(Spacer(1, 0.3 * inch))
    elements.append(Paragraph(
        "<b>Fractional engagements remain our core offering</b>, representing 42% of all 2025 engagements. "
        "This model provides companies with experienced technology executives at a fraction of the cost of a full-time hire.",
        styles['BodyText']
    ))

    elements.append(PageBreak())
    return elements


def build_performers_page(styles):
    """Build Top Performers page"""
    elements = []
    elements.append(Paragraph("Top Performers", styles['SectionHeader']))

    elements.append(Paragraph("Engagement Leaders", styles['SubHeader']))
    elements.append(Paragraph(
        "Partners who originated the most client engagements in 2025",
        styles['BodyText']
    ))

    engagement_leaders = [
        ['Partner', 'Engagements'],
        ['Richard Harris', '34'],
        ['Stephen Lavin', '25'],
        ['Brad Wheeler', '24'],
        ['Helmut Oehring', '15'],
        ['Jim Bridges', '11'],
        ['Greg Pascuzzi', '10'],
    ]

    leader_table = Table(engagement_leaders, colWidths=[3*inch, 1.2*inch])
    leader_table.setStyle(create_table_style())
    elements.append(leader_table)

    elements.append(Spacer(1, 0.3 * inch))
    elements.append(Paragraph("Revenue Leaders", styles['SubHeader']))
    elements.append(Paragraph(
        "Top delivering partners by client billings in 2025",
        styles['BodyText']
    ))

    revenue_leaders = [
        ['Partner', 'Revenue'],
        ['Simon Upton', '$1.04M'],
        ['John Hill', '$772K'],
        ['Brenton McKinney', '$759K'],
        ['Anna Naughton', '$647K'],
        ['Michelle Russell', '$615K'],
        ['Ihor Nadberezny', '$515K'],
        ['Troy Hollingsworth', '$467K'],
        ['Kirsten Garen', '$466K'],
        ['James Simmons', '$447K'],
        ['Deborah Cassidy', '$432K'],
    ]

    revenue_table = Table(revenue_leaders, colWidths=[3*inch, 1.2*inch])
    revenue_table.setStyle(create_table_style())
    elements.append(revenue_table)

    elements.append(PageBreak())
    return elements


def build_eos_page(styles):
    """Build Running on EOS page"""
    elements = []
    elements.append(Paragraph("Running on EOS", styles['SectionHeader']))
    elements.append(Paragraph("Operational Excellence Through Discipline", styles['SubHeader']))

    elements.append(Paragraph(
        "Fortium Partners runs on the Entrepreneurial Operating System (EOS), using Ninety.io to track our progress. "
        "This disciplined approach keeps our teams aligned, accountable, and focused on what matters most.",
        styles['BodyText']
    ))

    elements.append(Spacer(1, 0.2 * inch))

    # EOS Metrics
    elements.append(Paragraph("263+", styles['BigNumber']))
    elements.append(Paragraph("L10 Meetings Held", styles['NumberLabel']))
    elements.append(Spacer(1, 0.1 * inch))
    elements.append(Paragraph("225", styles['BigNumber']))
    elements.append(Paragraph("Issues Identified & Solved", styles['NumberLabel']))

    elements.append(Spacer(1, 0.3 * inch))

    eos_data = [
        ['Metric', 'Count'],
        ['L10 Meetings Held', '263+'],
        ['Issues Identified & Solved', '225'],
        ['To-Dos Completed', '70'],
        ['Quarterly Rocks Set', '25+'],
    ]

    eos_table = Table(eos_data, colWidths=[3*inch, 1.2*inch])
    eos_table.setStyle(create_table_style())
    elements.append(eos_table)

    elements.append(Spacer(1, 0.2 * inch))
    elements.append(Paragraph("Key Rocks Achieved", styles['SubHeader']))

    rocks = [
        "Website updates and SEO optimization",
        "Partner capital transaction policies",
        "Conference planning for March 2026",
        "Marketing collateral refresh",
        "Updated partner engagement checklist",
    ]

    for rock in rocks:
        elements.append(Paragraph(f"• {rock}", styles['BodyText']))

    elements.append(Spacer(1, 0.2 * inch))
    elements.append(Paragraph(
        "Our Leadership Team held <b>183 Level 10 meetings</b> in 2025—demonstrating the consistent "
        "weekly rhythm that keeps our organization moving forward.",
        styles['BodyText']
    ))

    elements.append(PageBreak())
    return elements


def build_future_page(styles):
    """Build Looking Ahead page"""
    elements = []
    elements.append(Paragraph("Looking Ahead to 2026", styles['SectionHeader']))

    priorities = [
        ("Expand Partner Network", "Continue recruiting top-tier technology executives across underserved markets"),
        ("Deepen Industry Expertise", "Develop specialized practice groups for healthcare, technology, and private equity"),
        ("Enhance Client Experience", "Invest in technology and processes that make engagements smoother and more impactful"),
        ("Strengthen Community", "More opportunities for partners to connect, learn, and collaborate"),
        ("Inaugural Partner Conference", "March 2026 in Plano, TX—bringing our network together"),
    ]

    for i, (title, desc) in enumerate(priorities, 1):
        elements.append(Paragraph(f"<b>{i}. {title}</b>", styles['SubHeader']))
        elements.append(Paragraph(desc, styles['BodyText']))
        elements.append(Spacer(1, 0.1 * inch))

    elements.append(PageBreak())
    return elements


def build_about_page(styles):
    """Build About page"""
    elements = []
    elements.append(Paragraph("About Fortium Partners", styles['SectionHeader']))

    elements.append(Spacer(1, 0.3 * inch))
    elements.append(Paragraph("<b>Fortium Partners, LP</b>", styles['BodyText']))
    elements.append(Paragraph("Founded May 6, 2014 | Plano, Texas", styles['BodyText']))

    elements.append(Spacer(1, 0.3 * inch))
    elements.append(Paragraph("<b>Our Mission</b>", styles['SubHeader']))
    elements.append(Paragraph(
        "To provide companies access to elite technology leadership through our national network of experienced CIOs, CTOs, and CISOs.",
        styles['BodyText']
    ))

    elements.append(Spacer(1, 0.3 * inch))
    elements.append(Paragraph("<b>Headquarters</b>", styles['SubHeader']))
    elements.append(Paragraph("6860 North Dallas Parkway, Suite 200", styles['BodyText']))
    elements.append(Paragraph("Plano, TX 75024", styles['BodyText']))

    elements.append(Spacer(1, 0.3 * inch))
    elements.append(Paragraph("<b>www.fortiumpartners.com</b>", ParagraphStyle(
        'Website', parent=styles['BodyText'], textColor=NAVY, fontName='Helvetica-Bold'
    )))

    return elements


def generate_pdf():
    """Generate the full PDF"""
    output_path = "Fortium_Partners_Year_in_Review_2025.pdf"

    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        rightMargin=0.75*inch,
        leftMargin=0.75*inch,
        topMargin=0.75*inch,
        bottomMargin=0.75*inch
    )

    styles = create_styles()
    elements = []

    # Build all pages
    elements.extend(build_cover_page(styles))
    elements.extend(build_letter_page(styles))
    elements.extend(build_numbers_page(styles))
    elements.extend(build_network_page(styles))
    elements.extend(build_clients_page(styles))
    elements.extend(build_delivery_page(styles))
    elements.extend(build_performers_page(styles))
    elements.extend(build_eos_page(styles))
    elements.extend(build_future_page(styles))
    elements.extend(build_about_page(styles))

    # Build the PDF
    doc.build(elements, onFirstPage=add_page_number, onLaterPages=add_page_number)

    print(f"PDF generated: {output_path}")
    print(f"File size: {os.path.getsize(output_path) / 1024:.1f} KB")
    return output_path


if __name__ == "__main__":
    generate_pdf()
