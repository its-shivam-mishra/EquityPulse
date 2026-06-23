import os
from io import BytesIO
from datetime import datetime
import math
from dotenv import load_dotenv
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
)
from reportlab.lib import pdfencrypt
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle


# Load env variables
load_dotenv()


def generate_portfolio_pdf(stocks_data: list) -> bytes:
    """
    Generate a professional PDF report of stocks, weights, and SMA status.
    Returns: Bytes of the generated PDF.
    """
    buffer = BytesIO()
    
    # Get password protection key if configured
    pdf_password = os.getenv("PDF_PASSWORD")
    encrypt_opts = None
    if pdf_password:
        pdf_password = pdf_password.strip().strip('"').strip("'")
        if pdf_password:
            encrypt_opts = pdfencrypt.StandardEncryption(userPassword=pdf_password)

    # 0.5 inch margins (36 points) for A4 (595.27 x 841.89 points)
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36,
        encrypt=encrypt_opts
    )
    
    story = []
    styles = getSampleStyleSheet()
    
    # Define custom styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=24,
        textColor=colors.HexColor('#0f172a'),
        spaceAfter=4
    )
    
    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9.5,
        leading=14,
        textColor=colors.HexColor('#64748b'),
        spaceAfter=15
    )
    
    section_title_style = ParagraphStyle(
        'SectionTitle',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=16,
        textColor=colors.HexColor('#1e293b'),
        spaceBefore=10,
        spaceAfter=8
    )
    
    cell_style = ParagraphStyle(
        'TableCell',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=10,
        textColor=colors.HexColor('#334155')
    )
    
    cell_bold_style = ParagraphStyle(
        'TableCellBold',
        parent=cell_style,
        fontName='Helvetica-Bold'
    )
    
    cell_right_style = ParagraphStyle(
        'TableCellRight',
        parent=cell_style,
        alignment=2
    )
    
    cell_right_bold_style = ParagraphStyle(
        'TableCellRightBold',
        parent=cell_bold_style,
        alignment=2
    )

    cell_center_style = ParagraphStyle(
        'TableCellCenter',
        parent=cell_style,
        alignment=1
    )
    
    cell_center_bold_style = ParagraphStyle(
        'TableCellCenterBold',
        parent=cell_bold_style,
        alignment=1
    )
    
    # 1. Header Section
    story.append(Paragraph("EquityPulse Portfolio Performance", title_style))
    story.append(Paragraph(f"Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Indian Stock Portfolio Analyzer", subtitle_style))
    
    # Calculate summary metrics (need total_current to compute weights)
    total_invested = 0.0
    total_current = 0.0
    total_today_return = 0.0
    
    for s in stocks_data:
        buying_price = float(s.get("buying_price", 0))
        quantity = float(s.get("quantity", 0))
        invested = buying_price * quantity
        total_invested += invested
        
        if s.get("status") == "success" and s.get("current_value") is not None:
            total_current += float(s.get("current_value"))
        else:
            total_current += invested
            
        # Accumulate today's return
        if s.get("status") == "success" and s.get("today_return_val") is not None:
            tr_val = s.get("today_return_val")
            if not math.isnan(tr_val):
                total_today_return += float(tr_val)
            
    # 2. Detailed Holdings Table (Columns: Symbol, Weight, Today's Return, Gain/Loss, SMA Status)
    story.append(Paragraph("Portfolio Holdings & SMA Indicators", section_title_style))
    
    # Table headers
    headers = [
        Paragraph("<b>Stock Symbol</b>", cell_bold_style),
        Paragraph("<b>Weight</b>", cell_right_bold_style),
        Paragraph("<b>Today's Return</b>", cell_right_bold_style),
        Paragraph("<b>Gain / Loss (%)</b>", cell_right_bold_style),
        Paragraph("<b>SMA Status (20 / 50 / 100 / 200)</b>", cell_center_bold_style)
    ]
    
    table_rows = [headers]
    
    for idx, s in enumerate(stocks_data):
        symbol = s.get("symbol", "")
        qty = float(s.get("quantity", 0))
        buy_price = float(s.get("buying_price", 0))
        current_price = s.get("current_price")
        
        invested_val = buy_price * qty
        current_val = float(s.get("current_value")) if s.get("current_value") is not None else invested_val
        weight_pct = (current_val / total_current * 100) if total_current > 0 else 0.0
        
        # Today's Return formatting
        today_return_val = s.get("today_return_val")
        today_change_pct = s.get("today_change_pct")
        if today_return_val is not None and not math.isnan(today_return_val):
            tr_color = "#15803d" if today_return_val >= 0 else "#b91c1c"
            tr_prefix = "+" if today_return_val >= 0 else "-"
            tr_pct_sign = "+" if today_change_pct >= 0 else ""
            abs_tr = abs(today_return_val)
            today_return_str = f"<font color='{tr_color}'><b>{tr_prefix}Rs. {abs_tr:,.2f}</b><br/>({tr_pct_sign}{today_change_pct:.2f}%)</font>"
        else:
            today_return_str = "—"

        # Gain/Loss formatting
        gain_loss_pct = s.get("gain_loss_pct")
        if gain_loss_pct is not None and not math.isnan(gain_loss_pct):
            gl_color = "#15803d" if gain_loss_pct >= 0 else "#b91c1c"
            gl_sign = "+" if gain_loss_pct >= 0 else ""
            gain_loss_pct_str = f"<font color='{gl_color}'>{gl_sign}{gain_loss_pct:.2f}%</font>"
        else:
            gain_loss_pct_str = "—"

        # SMA arrows formatting
        def make_sma_cell(curr_p, sma20, sma50, sma100, sma200):
            if curr_p is None:
                return Paragraph("<font color='#94a3b8'>N/A</font>", cell_center_style)
            
            def arrow_part(name, sma_val):
                if sma_val is None:
                    return f"{name}:—"
                color = "#15803d" if curr_p >= sma_val else "#b91c1c"
                arrow = "▲" if curr_p >= sma_val else "▼"
                return f"{name}:<font color='{color}'>{arrow}</font>"
            
            parts = [
                arrow_part("20", sma20),
                arrow_part("50", sma50),
                arrow_part("100", sma100),
                arrow_part("200", sma200)
            ]
            return Paragraph("  ".join(parts), cell_center_style)
            
        sma_cell = make_sma_cell(
            current_price,
            s.get("sma20"),
            s.get("sma50"),
            s.get("sma100"),
            s.get("sma200")
        )
        
        row_data = [
            Paragraph(f"<b>{symbol}</b>", cell_bold_style),
            Paragraph(f"{weight_pct:.2f}%", cell_right_style),
            Paragraph(today_return_str, cell_right_style),
            Paragraph(gain_loss_pct_str, cell_right_style),
            sma_cell
        ]
        table_rows.append(row_data)
        
    # Totals Row at the bottom
    total_gain_loss = total_current - total_invested
    total_gain_loss_pct = (total_gain_loss / total_invested * 100) if total_invested > 0 else 0.0
    total_gl_color = "#15803d" if total_gain_loss_pct >= 0 else "#b91c1c"
    total_gl_sign = "+" if total_gain_loss_pct >= 0 else ""
    total_gl_str = f"<font color='{total_gl_color}'><b>{total_gl_sign}{total_gain_loss_pct:.2f}%</b></font>"

    # Portfolio-wide today's return percent
    prev_total_current = total_current - total_today_return
    total_tr_color = "#15803d" if total_today_return >= 0 else "#b91c1c"
    total_tr_prefix = "+" if total_today_return >= 0 else "-"
    if prev_total_current > 0:
        total_tr_pct = (total_today_return / prev_total_current) * 100
        total_tr_pct_sign = "+" if total_tr_pct >= 0 else ""
        total_tr_pct_str = f"<br/>({total_tr_pct_sign}{total_tr_pct:.2f}%)"
    else:
        total_tr_pct_str = ""
    abs_total_tr = abs(total_today_return)
    total_tr_str = f"<font color='{total_tr_color}'><b>{total_tr_prefix}Rs. {abs_total_tr:,.2f}</b>{total_tr_pct_str}</font>"

    totals_row = [
        Paragraph("<b>TOTALS</b>", cell_bold_style),
        Paragraph("<b>100.00%</b>", cell_right_bold_style),
        Paragraph(total_tr_str, cell_right_bold_style),
        Paragraph(total_gl_str, cell_right_bold_style),
        Paragraph("", cell_center_bold_style)
    ]
    table_rows.append(totals_row)
    
    # Widths sum up to 520
    col_widths = [110, 60, 110, 90, 150]
    holdings_table = Table(table_rows, colWidths=col_widths, repeatRows=1)
    
    # Table Styling
    t_style = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e293b')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
        ('TOPPADDING', (0, 0), (-1, 0), 6),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.HexColor('#f8fafc')]),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#f1f5f9')),  # Totals background
        ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
        ('TOPPADDING', (0, 1), (-1, -1), 4),
    ]
    
    # Set header text color
    for col_idx in range(len(headers)):
        holdings_table.setStyle(TableStyle([
            ('TEXTCOLOR', (col_idx, 0), (col_idx, 0), colors.whitesmoke)
        ]))
        
    holdings_table.setStyle(TableStyle(t_style))
    story.append(holdings_table)
    
    # 3. Legend Section
    story.append(Spacer(1, 15))
    legend_text = (
        "<b>Legend</b>: Weight is calculated based on current market valuations (Invested + Returns). "
        "SMA arrows represent the current price position relative to the moving averages: "
        "<font color='#15803d'>▲ Above</font> or equal to SMA, "
        "<font color='#b91c1c'>▼ Below</font> SMA. — indicates insufficient historical data to compute."
    )
    legend_style = ParagraphStyle(
        'LegendStyle',
        parent=styles['Normal'],
        fontName='Helvetica-Oblique',
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor('#475569')
    )
    story.append(Paragraph(legend_text, legend_style))
    
    # Build Document
    doc.build(story)
    
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes

