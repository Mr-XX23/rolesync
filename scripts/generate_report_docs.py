import os
import re
import sys
import subprocess
from pathlib import Path
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
import markdown

WORKSPACE_DIR = Path(r"d:\Agent Ai\Role-Sync")
MD_FILE = WORKSPACE_DIR / "ROLESYNC_FINAL_YEAR_PROJECT_REPORT.md"
DOCX_FILE = WORKSPACE_DIR / "ROLESYNC_FINAL_YEAR_PROJECT_REPORT.docx"
HTML_FILE = WORKSPACE_DIR / "ROLESYNC_FINAL_YEAR_PROJECT_REPORT.html"
PDF_FILE = WORKSPACE_DIR / "ROLESYNC_FINAL_YEAR_PROJECT_REPORT.pdf"

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
if not os.path.exists(CHROME_PATH):
    CHROME_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

def set_cell_background(cell, fill_hex):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>')
    tcPr.append(shd)

def set_cell_margins(cell, top=100, bottom=100, left=150, right=150):
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = parse_xml(f'<w:tcMar {nsdecls("w")}><w:top w:w="{top}" w:type="dxa"/><w:bottom w:w="{bottom}" w:type="dxa"/><w:left w:w="{left}" w:type="dxa"/><w:right w:w="{right}" w:type="dxa"/></w:tcMar>')
    tcPr.append(tcMar)

def set_table_borders(table, color="D3D3D3"):
    tblPr = table._tbl.tblPr
    borders = parse_xml(
        f'<w:tblBorders {nsdecls("w")}>'
        f'<w:top w:val="single" w:sz="4" w:space="0" w:color="{color}"/>'
        f'<w:bottom w:val="single" w:sz="6" w:space="0" w:color="{color}"/>'
        f'<w:insideH w:val="single" w:sz="4" w:space="0" w:color="{color}"/>'
        f'<w:insideV w:val="none"/>'
        f'<w:left w:val="none"/>'
        f'<w:right w:val="none"/>'
        f'</w:tblBorders>'
    )
    tblPr.append(borders)

def build_docx(md_path, docx_path):
    print("Generating DOCX file...")
    doc = docx.Document()
    
    # Page setup - Margins (1 inch top, bottom, right; 1.25 inch left for binding)
    sections = doc.sections
    for s in sections:
        s.top_margin = Inches(1.0)
        s.bottom_margin = Inches(1.0)
        s.left_margin = Inches(1.2)
        s.right_margin = Inches(1.0)
        s.page_width = Inches(8.27)  # A4
        s.page_height = Inches(11.69)
        
        # Add page numbering to footer
        footer = s.footer
        f_p = footer.paragraphs[0]
        f_p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        f_run = f_p.add_run("RoleSync Final Year Project Report  |  Page ")
        f_run.font.name = "Calibri"
        f_run.font.size = Pt(9)
        f_run.font.color.rgb = RGBColor(128, 128, 128)
        
        # XML page number
        f_p_xml = f_p._p
        fldSimple = parse_xml(r'<w:fldSimple %s w:instr="PAGE"/>' % nsdecls('w'))
        f_p_xml.append(fldSimple)

    # Styles
    styles = doc.styles
    normal_style = styles['Normal']
    normal_style.font.name = 'Times New Roman'
    normal_style.font.size = Pt(12)
    normal_style.font.color.rgb = RGBColor(30, 41, 59)
    normal_style.paragraph_format.line_spacing = 1.15
    normal_style.paragraph_format.space_after = Pt(6)

    with open(md_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    in_code_block = False
    code_buffer = []
    code_lang = ""
    table_buffer = []
    in_table = False

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Handle page breaks
        if stripped == "\\newpage" or stripped == "\\pagebreak":
            doc.add_page_break()
            i += 1
            continue

        # Handle Code blocks
        if stripped.startswith("```"):
            if not in_code_block:
                in_code_block = True
                code_lang = stripped[3:].strip()
                code_buffer = []
            else:
                in_code_block = False
                # flush code block
                full_code = "\n".join(code_buffer)
                p = doc.add_paragraph()
                p.paragraph_format.left_indent = Inches(0.25)
                p.paragraph_format.right_indent = Inches(0.25)
                p.paragraph_format.space_before = Pt(4)
                p.paragraph_format.space_after = Pt(6)
                p.paragraph_format.line_spacing = 1.0
                
                # We can put code inside a 1x1 table with gray background
                code_table = doc.add_table(rows=1, cols=1)
                code_table.alignment = WD_TABLE_ALIGNMENT.CENTER
                cell = code_table.cell(0, 0)
                set_cell_background(cell, "F1F5F9")
                set_cell_margins(cell, top=140, bottom=140, left=200, right=200)
                cp = cell.paragraphs[0]
                cp.paragraph_format.space_after = Pt(0)
                cp.paragraph_format.line_spacing = 1.0
                run = cp.add_run(full_code)
                run.font.name = 'Consolas'
                run.font.size = Pt(9.5)
                run.font.color.rgb = RGBColor(15, 23, 42)
                
                # Add tiny spacing after table
                sp = doc.add_paragraph()
                sp.paragraph_format.space_before = Pt(2)
                sp.paragraph_format.space_after = Pt(2)

            i += 1
            continue

        if in_code_block:
            code_buffer.append(line.rstrip('\r\n'))
            i += 1
            continue

        # Handle Markdown Tables
        if "|" in stripped and (stripped.startswith("|") or stripped.endswith("|")):
            table_buffer.append(stripped)
            # check if next line is table
            if i + 1 < len(lines) and "|" in lines[i+1].strip():
                i += 1
                continue
            else:
                # process table buffer
                rows_data = []
                for tline in table_buffer:
                    # check if separator row
                    if re.match(r'^[\|\s\-\:\+]+$', tline):
                        continue
                    cols = [c.strip() for c in tline.strip('|').split('|')]
                    rows_data.append(cols)
                
                if rows_data:
                    num_rows = len(rows_data)
                    num_cols = max(len(r) for r in rows_data)
                    tbl = doc.add_table(rows=num_rows, cols=num_cols)
                    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
                    set_table_borders(tbl)

                    for r_idx, r_data in enumerate(rows_data):
                        row = tbl.rows[r_idx]
                        is_header = (r_idx == 0)
                        for c_idx in range(num_cols):
                            cell = row.cells[c_idx]
                            set_cell_margins(cell, top=100, bottom=100, left=140, right=140)
                            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
                            val = r_data[c_idx] if c_idx < len(r_data) else ""
                            cp = cell.paragraphs[0]
                            cp.paragraph_format.space_after = Pt(2)
                            cp.paragraph_format.space_before = Pt(2)
                            cp.paragraph_format.line_spacing = 1.05

                            if is_header:
                                set_cell_background(cell, "0F172A") # Navy header
                                run = cp.add_run(val)
                                run.bold = True
                                run.font.name = "Calibri"
                                run.font.size = Pt(10)
                                run.font.color.rgb = RGBColor(255, 255, 255)
                            else:
                                if r_idx % 2 == 1:
                                    set_cell_background(cell, "F8FAFC")
                                else:
                                    set_cell_background(cell, "FFFFFF")
                                run = cp.add_run(val)
                                run.font.name = "Calibri"
                                run.font.size = Pt(9.5)
                                run.font.color.rgb = RGBColor(30, 41, 59)

                    tbl_spacer = doc.add_paragraph()
                    tbl_spacer.paragraph_format.space_before = Pt(4)
                    tbl_spacer.paragraph_format.space_after = Pt(6)

                table_buffer = []
                i += 1
                continue

        # Handle Headings
        if stripped.startswith("# "):
            title_text = stripped[2:].strip()
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(16)
            p.paragraph_format.space_after = Pt(8)
            p.paragraph_format.keep_with_next = True
            run = p.add_run(title_text)
            run.font.name = 'Calibri'
            run.font.size = Pt(20)
            run.bold = True
            run.font.color.rgb = RGBColor(15, 23, 42)
            if "FINAL YEAR PROJECT" in title_text or "ASIA e UNIVERSITY" in title_text or "ROLESYNC" in title_text:
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            i += 1
            continue

        if stripped.startswith("## "):
            h2_text = stripped[3:].strip()
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(14)
            p.paragraph_format.space_after = Pt(6)
            p.paragraph_format.keep_with_next = True
            run = p.add_run(h2_text)
            run.font.name = 'Calibri'
            run.font.size = Pt(15)
            run.bold = True
            run.font.color.rgb = RGBColor(30, 58, 138)  # Deep Royal Blue
            if "APPROVED SHEET" in h2_text or "DECLARATION" in h2_text or "ACKNOWLEDGEMENT" in h2_text or "ABSTRACT" in h2_text or "TABLE OF CONTENTS" in h2_text:
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            i += 1
            continue

        if stripped.startswith("### "):
            h3_text = stripped[4:].strip()
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(10)
            p.paragraph_format.space_after = Pt(4)
            p.paragraph_format.keep_with_next = True
            run = p.add_run(h3_text)
            run.font.name = 'Calibri'
            run.font.size = Pt(13)
            run.bold = True
            run.font.color.rgb = RGBColor(15, 23, 42)
            if "SCHOOL OF SCIENCE" in h3_text or "VIRINCHI COLLEGE" in h3_text:
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            i += 1
            continue

        if stripped.startswith("#### "):
            h4_text = stripped[5:].strip()
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(8)
            p.paragraph_format.space_after = Pt(2)
            p.paragraph_format.keep_with_next = True
            run = p.add_run(h4_text)
            run.font.name = 'Calibri'
            run.font.size = Pt(11.5)
            run.bold = True
            run.font.color.rgb = RGBColor(51, 65, 85)
            i += 1
            continue

        # Handle Bullet points
        if stripped.startswith("- ") or stripped.startswith("* "):
            bullet_text = stripped[2:].strip()
            p = doc.add_paragraph(style='List Bullet')
            p.paragraph_format.space_after = Pt(3)
            p.paragraph_format.line_spacing = 1.15
            
            # Parse bold runs inside bullet
            parse_styled_text(p, bullet_text)
            i += 1
            continue

        # Handle blockquote / note
        if stripped.startswith("> "):
            quote_text = stripped[2:].strip()
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Inches(0.3)
            p.paragraph_format.space_after = Pt(4)
            run = p.add_run(quote_text)
            run.italic = True
            run.font.name = 'Times New Roman'
            run.font.size = Pt(11)
            run.font.color.rgb = RGBColor(71, 85, 105)
            i += 1
            continue

        # Skip horizontal rules
        if stripped == "---" or stripped == "***":
            i += 1
            continue

        # Normal paragraph
        if stripped:
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(6)
            p.paragraph_format.line_spacing = 1.15
            if "Submitted in partial fulfilment" in stripped or "Submitted By:" in stripped or "Under the Supervision of:" in stripped or "August, 2026" in stripped:
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            parse_styled_text(p, stripped)

        i += 1

    doc.save(docx_path)
    print(f"DOCX created successfully at: {docx_path}")

def parse_styled_text(paragraph, text):
    """Parses markdown bold, italic, inline code in text into docx runs."""
    # Split text into tokens by **bold** or `code` or *italic*
    pattern = re.compile(r'(\*\*.*?\*\*|\*.*?\*|`.*?`)')
    tokens = pattern.split(text)
    for token in tokens:
        if not token:
            continue
        if token.startswith("**") and token.endswith("**"):
            run = paragraph.add_run(token[2:-2])
            run.bold = True
            run.font.name = "Times New Roman"
        elif token.startswith("*") and token.endswith("*"):
            run = paragraph.add_run(token[1:-1])
            run.italic = True
            run.font.name = "Times New Roman"
        elif token.startswith("`") and token.endswith("`"):
            run = paragraph.add_run(token[1:-1])
            run.font.name = "Consolas"
            run.font.size = Pt(10)
            run.font.color.rgb = RGBColor(194, 24, 91)
        else:
            run = paragraph.add_run(token)
            run.font.name = "Times New Roman"

def build_html_and_pdf(md_path, html_path, pdf_path):
    print("Generating Academic HTML and PDF...")
    with open(md_path, 'r', encoding='utf-8') as f:
        md_text = f.read()

    # Pre-process \newpage into HTML page break
    processed_md = re.sub(r'\\newpage|\\pagebreak', '<div class="page-break"></div>', md_text)
    # Also handle markdown tables and code blocks via markdown library
    html_body = markdown.markdown(
        processed_md,
        extensions=['tables', 'fenced_code', 'codehilite', 'toc']
    )

    academic_css = """
    @page {
        size: A4;
        margin: 2.5cm 2.2cm 2.5cm 2.8cm;
        @bottom-right {
            content: "RoleSync Capstone Report | Page " counter(page);
            font-size: 8.5pt;
            font-family: "Segoe UI", Arial, sans-serif;
            color: #64748b;
        }
    }
    body {
        font-family: "Times New Roman", Times, Georgia, serif;
        font-size: 11.5pt;
        line-height: 1.5;
        color: #1e293b;
        background-color: #ffffff;
        margin: 0;
        padding: 0;
    }
    h1, h2, h3, h4, h5, h6 {
        font-family: "Segoe UI", "Calibri", Arial, sans-serif;
        color: #0f172a;
        font-weight: 700;
        page-break-after: avoid;
    }
    h1 {
        font-size: 20pt;
        margin-top: 24pt;
        margin-bottom: 12pt;
        border-bottom: 1.5px solid #cbd5e1;
        padding-bottom: 4pt;
    }
    h2 {
        font-size: 15pt;
        margin-top: 20pt;
        margin-bottom: 8pt;
        color: #1e3a8a;
    }
    h3 {
        font-size: 12.5pt;
        margin-top: 14pt;
        margin-bottom: 6pt;
    }
    p {
        margin-top: 0;
        margin-bottom: 8pt;
        text-align: justify;
    }
    ul, ol {
        margin-top: 0;
        margin-bottom: 8pt;
        padding-left: 20pt;
    }
    li {
        margin-bottom: 3pt;
    }
    .page-break {
        page-break-before: always;
        break-before: page;
    }
    table {
        width: 100%;
        border-collapse: collapse;
        margin: 12pt 0;
        font-family: "Segoe UI", Arial, sans-serif;
        font-size: 9.5pt;
        page-break-inside: avoid;
    }
    th {
        background-color: #0f172a;
        color: #ffffff;
        text-align: left;
        padding: 7pt 9pt;
        font-weight: 600;
        border: 1px solid #0f172a;
    }
    td {
        padding: 6pt 9pt;
        border: 1px solid #e2e8f0;
        vertical-align: middle;
    }
    tr:nth-child(even) {
        background-color: #f8fafc;
    }
    pre, code {
        font-family: "Consolas", "Courier New", monospace;
        background-color: #f1f5f9;
        border-radius: 4pt;
    }
    pre {
        padding: 9pt 12pt;
        font-size: 9pt;
        line-height: 1.35;
        border: 1px solid #cbd5e1;
        overflow-x: auto;
        page-break-inside: avoid;
        color: #0f172a;
    }
    code {
        font-size: 9.5pt;
        padding: 1pt 3pt;
        color: #be185d;
    }
    hr {
        border: 0;
        height: 1px;
        background: #cbd5e1;
        margin: 14pt 0;
    }
    blockquote {
        margin: 8pt 0;
        padding: 6pt 12pt;
        border-left: 4px solid #3b82f6;
        background-color: #eff6ff;
        color: #1e40af;
        font-style: italic;
    }
    .cover-page {
        text-align: center;
        page-break-after: always;
        padding-top: 40pt;
    }
    """

    full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>RoleSync Final Year Project Report</title>
    <style>
        {academic_css}
    </style>
</head>
<body>
    {html_body}
</body>
</html>
"""

    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(full_html)
    print(f"HTML created successfully at: {html_path}")

    # Generate PDF using Chrome Headless
    if os.path.exists(CHROME_PATH):
        print(f"Executing browser print-to-pdf using: {CHROME_PATH}")
        cmd = [
            CHROME_PATH,
            "--headless=new",
            "--disable-gpu",
            "--run-all-compositor-stages-before-draw",
            "--no-pdf-header-footer",
            f"--print-to-pdf={pdf_path}",
            str(html_path)
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0 and os.path.exists(pdf_path):
            print(f"PDF generated successfully at: {pdf_path}")
        else:
            print("Headless browser error:", res.stderr)
    else:
        print("Chrome or Edge executable not found for automated PDF export.")

if __name__ == "__main__":
    build_docx(MD_FILE, DOCX_FILE)
    build_html_and_pdf(MD_FILE, HTML_FILE, PDF_FILE)
