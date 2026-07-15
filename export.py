import os
import sys
import subprocess
import time
import datetime
import shutil

# --- Self-Bootstrapping Venv Setup ---
def setup_venv():
    # Define paths
    script_dir = os.path.dirname(os.path.abspath(__file__))
    venv_dir = os.path.join(script_dir, ".venv")
    
    if os.name == 'nt':
        venv_python = os.path.join(venv_dir, "Scripts", "python.exe")
        venv_pip = os.path.join(venv_dir, "Scripts", "pip.exe")
        venv_playwright = os.path.join(venv_dir, "Scripts", "playwright.exe")
    else:
        venv_python = os.path.join(venv_dir, "bin", "python")
        venv_pip = os.path.join(venv_dir, "bin", "pip")
        venv_playwright = os.path.join(venv_dir, "bin", "playwright")

    # Check if we are already running inside the virtual environment
    if sys.executable.lower() == venv_python.lower():
        return

    print("=" * 60)
    print("Initializing environment...")
    print("=" * 60)

    # 1. Create venv if not present
    if not os.path.exists(venv_dir):
        print(f"Creating virtual environment in {venv_dir}...")
        subprocess.run([sys.executable, "-m", "venv", venv_dir], check=True)

    # 2. Upgrade pip and install requirements
    print("Installing/upgrading dependencies (playwright, pypdf)...")
    subprocess.run([venv_python, "-m", "pip", "install", "--upgrade", "pip"], check=True)
    subprocess.run([venv_python, "-m", "pip", "install", "playwright", "pypdf"], check=True)

    # 3. Ensure playwright browsers are installed
    print("Installing Playwright Chromium browser...")
    subprocess.run([venv_playwright, "install", "chromium"], check=True)

    print("Environment setup complete. Relaunching script in virtual environment...")
    print("=" * 60 + "\n")
    
    # Relaunch script
    result = subprocess.run([venv_python, __file__] + sys.argv[1:])
    sys.exit(result.returncode)

# Run setup if not already in venv
setup_venv()

# --- Main Program Logic (Executed inside venv) ---
from playwright.sync_api import sync_playwright
from pypdf import PdfWriter, PdfReader

def print_page_to_pdf(page, pdf_path):
    """Prints current page to A4 PDF with header, footer, and margins."""
    page.pdf(
        path=pdf_path,
        format="A4",
        print_background=True,
        display_header_footer=True,
        header_template='<div style="font-size: 8px; width: 100%; text-align: right; padding-right: 20px; color: #888;">Mobimo Export</div>',
        footer_template=(
            '<div style="font-size: 8px; width: 100%; display: flex; justify-content: space-between; padding: 0 20px; color: #888;">'
            '<span style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 400px;">URL: <span class="url"></span></span>'
            '<span>Printed: <span class="date"></span> | Page <span class="pageNumber"></span> of <span class="totalPages"></span></span>'
            '</div>'
        ),
        margin={
            "top": "50px",
            "bottom": "50px",
            "left": "30px",
            "right": "30px"
        }
    )

def safe_goto(page, url, timeout=30000):
    """Navigates to a URL safely, handling redirect interruptions."""
    try:
        page.goto(url, wait_until="commit", timeout=timeout)
    except Exception as e:
        if any(term in str(e).lower() for term in ["interrupted", "navigation", "abort", "transition"]):
            # Ignore redirect interruptions
            pass
        else:
            raise e
            
    # Try waiting for the page load to settle
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        try:
            page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass

def collect_urls_and_print_tables(page, base_url, detail_patterns, output_pdf_prefix, temp_dir):
    """Navigates to list page, paginates, saves table PDFs, and returns detail links."""
    print(f"\nNavigating to {base_url}...")
    safe_goto(page, base_url)
    
    # Wait for the login if redirected
    if "ciamlogin" in page.url.lower() or "login" in page.url.lower():
        print("Redirected to login. Waiting for you to complete login...")
        while "ciamlogin" in page.url.lower() or "login" in page.url.lower():
            time.sleep(1)
        print("Login detected, proceeding...")
        time.sleep(2)
        safe_goto(page, base_url)
        
    collected_links = set()
    page_num = 1
    table_pdfs = []
    last_content = ""
    
    while True:
        print(f"Processing list page {page_num}...")
        
        # 1. Print the list page to PDF
        pdf_path = os.path.join(temp_dir, f"{output_pdf_prefix}_list_{page_num}.pdf")
        print_page_to_pdf(page, pdf_path)
        table_pdfs.append(pdf_path)
        
        # 2. Extract links matching details patterns
        links = page.evaluate("""(patterns) => {
            const urls = [];
            const anchors = document.querySelectorAll('a');
            for (const a of anchors) {
                if (a.href) {
                    const hrefLower = a.href.toLowerCase();
                    if (patterns.some(p => hrefLower.includes(p.toLowerCase()))) {
                        urls.push(a.href);
                    }
                }
            }
            return urls;
        }""", detail_patterns)
        
        for url in links:
            collected_links.add(url)
            
        print(f"Page {page_num}: Found {len(links)} links. Total unique links: {len(collected_links)}")
        
        # Guard against infinite loops or static pages
        current_content = page.content()
        if page_num > 1 and current_content == last_content:
            print("Page content did not change. Stopping pagination.")
            break
        last_content = current_content
        
        # 3. Find and click the 'Next' pagination button
        next_clicked = page.evaluate("""() => {
            // 1. Specifically target Microsoft PowerPages entity-pager-next-link
            const nextButton = document.querySelector('a.entity-pager-next-link');
            if (nextButton && nextButton.getAttribute('aria-disabled') !== 'true') {
                nextButton.click();
                return true;
            }
            
            // 2. Fallback to strict text indicators if the class isn't used
            const elements = Array.from(document.querySelectorAll('a, button, [role="button"]'));
            const nextIndicators = ['>', '»', 'chevron-right', 'arrow-right'];
            const exactWords = ['next', 'nächste', 'nächst', 'weiter'];
            
            for (const el of elements) {
                const text = (el.textContent || '').trim().toLowerCase();
                const ariaLabel = (el.getAttribute('aria-label') || '').trim().toLowerCase();
                const className = (el.className || '').toLowerCase();
                const title = (el.getAttribute('title') || '').toLowerCase();
                
                // Skip disabled elements
                if (el.disabled || el.classList.contains('disabled') || el.getAttribute('aria-disabled') === 'true') {
                    continue;
                }
                
                // Ignore footer and policy links containing "weiter"
                if (el.href && (el.href.includes('privacy') || el.href.includes('datenschutz') || el.href.includes('policy'))) {
                    continue;
                }
                
                const matchesText = nextIndicators.some(ind => text === ind || text.includes(ind)) || 
                                    exactWords.some(word => text === word || ariaLabel === word || title === word);
                const matchesAria = nextIndicators.some(ind => ariaLabel.includes(ind));
                const matchesTitle = nextIndicators.some(ind => title.includes(ind));
                const matchesClass = className.includes('pagination-next');
                
                if (matchesText || matchesAria || matchesTitle || matchesClass) {
                    el.click();
                    return true;
                }
            }
            return false;
        }""")
        
        if not next_clicked:
            print("No active 'Next' page button found. Done.")
            break
            
        page_num += 1
        page.wait_for_timeout(3000)  # Wait for AJAX transition
        page.wait_for_load_state("networkidle")
        
    return list(collected_links), table_pdfs

def scrape_and_print_details(page, urls, type_label, temp_dir):
    """Visits each detail page, expands textareas, scrapes metadata, and prints PDF."""
    print(f"\nProcessing {len(urls)} details for {type_label}...")
    detail_records = []
    detail_pdfs = []
    
    for idx, url in enumerate(urls, 1):
        print(f"[{idx}/{len(urls)}] Opening detail: {url}")
        safe_goto(page, url)
        time.sleep(1.5)  # Buffer for loading dynamic details
        
        # Expand scrollable textareas and remove limits
        page.evaluate("""() => {
            // 1. Expand textareas
            document.querySelectorAll('textarea').forEach(el => {
                el.style.height = 'auto';
                el.style.height = (el.scrollHeight + 12) + 'px';
                el.style.overflow = 'visible';
                el.style.maxHeight = 'none';
                el.style.resize = 'none';
            });
            
            // 2. Clear height limits on scrollable ancestors
            document.querySelectorAll('*').forEach(el => {
                const style = window.getComputedStyle(el);
                if (style.overflowY === 'auto' || style.overflowY === 'scroll') {
                    el.style.overflow = 'visible';
                    el.style.maxHeight = 'none';
                    el.style.height = 'auto';
                }
            });
        }""")
        
        # Scrape basic metadata for the table of contents
        metadata = page.evaluate("""(args) => {
            const url = args.url;
            const type_label = args.type_label;
            let title = '';
            let date = '';
            let status = '';
            
            // Try to find a reasonable heading/title
            const headers = Array.from(document.querySelectorAll('h1, h2, h3, .card-title, .case-title'));
            for (const h of headers) {
                const text = (h.textContent || '').trim();
                if (text && !text.toLowerCase().includes('mobimo') && !text.toLowerCase().includes('portal') && text.length > 2) {
                    title = text;
                    break;
                }
            }
            
            // Search document body for date formats like dd.mm.yyyy or yyyy-mm-dd
            const bodyText = document.body.innerText || '';
            const dateMatch = bodyText.match(/\\b\\d{2}\\.\\d{2}\\.\\d{4}\\b/) || bodyText.match(/\\b\\d{4}-\\d{2}-\\d{2}\\b/);
            if (dateMatch) {
                date = dateMatch[0];
            }
            
            // Try to find status badges or fields
            const statusElements = Array.from(document.querySelectorAll('.badge, .status, [class*="status"]'));
            for (const se of statusElements) {
                const text = (se.textContent || '').trim();
                if (text && text.length < 25) {
                    status = text;
                    break;
                }
            }
            
            const urlObj = new URL(url);
            const id = urlObj.searchParams.get('id') || 'Unknown';
            
            return {
                id: id,
                title: title || `Record ${id.substring(0, 8)}`,
                date: date || 'N/A',
                status: status || 'N/A',
                url: url,
                type: type_label
            };
        }""", {"url": url, "type_label": type_label})
        
        detail_records.append(metadata)
        
        # Print the page to PDF
        pdf_path = os.path.join(temp_dir, f"{type_label}_detail_{idx}.pdf")
        print_page_to_pdf(page, pdf_path)
        detail_pdfs.append(pdf_path)
        
    return detail_records, detail_pdfs

def generate_cover_page(page, cases, defects, pdf_path):
    """Generates a beautiful HTML cover page with TOC and metadata, and prints it to PDF."""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Create HTML table rows for cases
    cases_rows = ""
    for idx, item in enumerate(cases, 1):
        cases_rows += f"""
        <tr>
            <td>{idx}</td>
            <td><strong>{item['title']}</strong></td>
            <td><code>{item['id'][:8]}...</code></td>
            <td>{item['date']}</td>
            <td><span class="status-tag">{item['status']}</span></td>
        </tr>
        """
        
    # Create HTML table rows for defects
    defects_rows = ""
    for idx, item in enumerate(defects, 1):
        defects_rows += f"""
        <tr>
            <td>{idx}</td>
            <td><strong>{item['title']}</strong></td>
            <td><code>{item['id'][:8]}...</code></td>
            <td>{item['date']}</td>
            <td><span class="status-tag">{item['status']}</span></td>
        </tr>
        """
        
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Mobimo deficiencies Export Archive</title>
        <style>
            body {{
                font-family: 'Segoe UI', Arial, sans-serif;
                margin: 40px;
                color: #2c3e50;
                line-height: 1.4;
            }}
            .header-box {{
                border-bottom: 3px solid #3498db;
                padding-bottom: 15px;
                margin-bottom: 30px;
            }}
            .title {{
                font-size: 28px;
                font-weight: bold;
                color: #1a252f;
                margin: 0;
            }}
            .subtitle {{
                font-size: 14px;
                color: #7f8c8d;
                margin: 5px 0 0 0;
            }}
            .meta-table {{
                width: 100%;
                border-collapse: collapse;
                margin-bottom: 25px;
            }}
            .meta-table td {{
                padding: 6px 12px;
                font-size: 13px;
            }}
            .meta-table td.label {{
                font-weight: bold;
                color: #34495e;
                width: 150px;
            }}
            h2 {{
                font-size: 18px;
                border-bottom: 1px solid #bdc3c7;
                padding-bottom: 5px;
                margin-top: 25px;
                color: #2c3e50;
            }}
            .stat-container {{
                display: flex;
                gap: 15px;
                margin-bottom: 20px;
            }}
            .stat-card {{
                flex: 1;
                background: #f8f9fa;
                border-left: 4px solid #3498db;
                padding: 10px 15px;
                border-radius: 4px;
            }}
            .stat-card .num {{
                font-size: 22px;
                font-weight: bold;
                color: #2c3e50;
            }}
            .stat-card .label {{
                font-size: 12px;
                color: #7f8c8d;
            }}
            .data-table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 10px;
                font-size: 11px;
            }}
            .data-table th, .data-table td {{
                border: 1px solid #e2e8f0;
                padding: 6px 10px;
                text-align: left;
            }}
            .data-table th {{
                background-color: #f8f9fa;
                color: #4a5568;
                font-weight: 600;
            }}
            .status-tag {{
                display: inline-block;
                background-color: #edf2f7;
                color: #4a5568;
                padding: 2px 6px;
                border-radius: 4px;
                font-size: 10px;
                font-weight: bold;
            }}
            .page-break {{
                page-break-after: always;
            }}
        </style>
    </head>
    <body>
        <div class="header-box">
            <div class="title">Mobimo Deficiencies & Cases Export Archive</div>
            <div class="subtitle">Personal archive copy generated on {now}</div>
        </div>
        
        <table class="meta-table">
            <tr>
                <td class="label">Source Portal</td>
                <td><a href="https://tenant.portal.mobimo.ch/">https://tenant.portal.mobimo.ch/</a></td>
            </tr>
            <tr>
                <td class="label">Date of Archive</td>
                <td>{now}</td>
            </tr>
        </table>

        <h2>Export Summary</h2>
        <div class="stat-container">
            <div class="stat-card">
                <div class="num">{len(cases)}</div>
                <div class="label">General Cases (Mängel)</div>
            </div>
            <div class="stat-card">
                <div class="num">{len(defects)}</div>
                <div class="label">Construction Defects (Baumängel)</div>
            </div>
        </div>

        <h2>Table of Contents / Document Index</h2>
        <p style="font-size: 12px;">This document compiles all tables and individual detail reports sequentially:</p>
        <ol style="font-size: 12px; line-height: 1.6;">
            <li>Archive Overview & Record Index (this document)</li>
            <li>General Cases List Table Page(s)</li>
            <li>Construction Defects List Table Page(s)</li>
            <li>Detailed Case Reports</li>
            <li>Detailed Construction Defect Reports</li>
        </ol>

        <div class="page-break"></div>

        <h2>General Cases Index ({len(cases)})</h2>
        {f'<table class="data-table"><thead><tr><th>#</th><th>Subject/Title</th><th>Case ID</th><th>Date</th><th>Status</th></tr></thead><tbody>{cases_rows}</tbody></table>' if cases else '<p style="font-size:12px; color:#7f8c8d;">No cases exported.</p>'}

        <div class="page-break"></div>

        <h2>Construction Defects Index ({len(defects)})</h2>
        {f'<table class="data-table"><thead><tr><th>#</th><th>Subject/Title</th><th>Defect ID</th><th>Date</th><th>Status</th></tr></thead><tbody>{defects_rows}</tbody></table>' if defects else '<p style="font-size:12px; color:#7f8c8d;">No defects exported.</p>'}
    </body>
    </html>
    """
    
    page.set_content(html_content)
    page.pdf(
        path=pdf_path,
        format="A4",
        print_background=True,
        margin={"top": "40px", "bottom": "40px", "left": "40px", "right": "40px"}
    )

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Export Mobimo deficiencies portal to a single PDF.")
    parser.add_argument("--cdp", type=int, help="Port of a running Chrome instance with remote debugging enabled.")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    temp_dir = os.path.join(script_dir, "temp_export_pdfs")
    
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    os.makedirs(temp_dir, exist_ok=True)
    
    output_pdf_path = os.path.join(script_dir, "deficiencies_report.pdf")

    with sync_playwright() as p:
        if args.cdp:
            print(f"Connecting to existing Chrome instance on port {args.cdp}...")
            browser = p.chromium.connect_over_cdp(f"http://localhost:{args.cdp}")
            
            # Search open pages for the mobimo portal tab
            page = None
            for ctx in browser.contexts:
                for pg in ctx.pages:
                    if "tenant.portal.mobimo.ch" in pg.url:
                        page = pg
                        break
                if page:
                    break
            
            if page:
                print(f"Found active Mobimo tab: {page.url}")
            else:
                print("Could not find an active tab for 'tenant.portal.mobimo.ch'. Creating a new tab.")
                context = browser.contexts[0] if browser.contexts else browser.new_context()
                page = context.new_page()
                safe_goto(page, "https://tenant.portal.mobimo.ch/DE/cases/")
            
            print("\n" + "="*80)
            print("CONNECTED OVER CDP:")
            print("1. Make sure you are logged in on the Mobimo portal tab.")
            print("2. Return to this terminal and press ENTER to start the export.")
            print("="*80 + "\n")
            input("Press ENTER here to start the export...")
        else:
            # Launch headed chromium browser
            print("Launching Chrome...")
            browser = p.chromium.launch(headless=False)
            context = browser.new_context(viewport={"width": 1280, "height": 800})
            page = context.new_page()

            # Step 1: Request user login
            cases_base_url = "https://tenant.portal.mobimo.ch/DE/cases/"
            print(f"Navigating to login page: {cases_base_url}")
            safe_goto(page, cases_base_url)

            print("\n" + "="*80)
            print("ACTION REQUIRED:")
            print("1. Log in manually in the opened browser window.")
            print("2. Ensure you are logged in and can view your cases.")
            print("3. Return to this command window and press ENTER to start the automation.")
            print("="*80 + "\n")
            input("Press ENTER here to start the export once you have logged in...")

        # Step 2: Extract Cases Table and links
        cases_links, cases_table_pdfs = collect_urls_and_print_tables(
            page=page,
            base_url="https://tenant.portal.mobimo.ch/DE/cases/",
            detail_patterns=["/cases/Case-Details/"],
            output_pdf_prefix="cases",
            temp_dir=temp_dir
        )

        # Step 3: Extract Construction Defects Table and links
        defects_links, defects_table_pdfs = collect_urls_and_print_tables(
            page=page,
            base_url="https://tenant.portal.mobimo.ch/DE/construction-defects/",
            detail_patterns=["/Construction-Defects/Construction-Defect-Details/"],
            output_pdf_prefix="defects",
            temp_dir=temp_dir
        )

        # Step 4: Extract all Cases Details and expand textareas
        cases_metadata, cases_detail_pdfs = scrape_and_print_details(
            page=page,
            urls=cases_links,
            type_label="Case",
            temp_dir=temp_dir
        )

        # Step 5: Extract all Defects Details and expand textareas
        defects_metadata, defects_detail_pdfs = scrape_and_print_details(
            page=page,
            urls=defects_links,
            type_label="Defect",
            temp_dir=temp_dir
        )

        # Step 6: Generate Table of Contents Cover PDF
        print("\nGenerating cover page and index...")
        cover_pdf_path = os.path.join(temp_dir, "cover.pdf")
        generate_cover_page(page, cases_metadata, defects_metadata, cover_pdf_path)

        # Close browser session (only if we launched it)
        if not args.cdp:
            browser.close()

        # Step 7: Merge all PDFs
        print("\nMerging all PDFs into deficiencies_report.pdf...")
        writer = PdfWriter()

        # Order of files in final output:
        # 1. Cover / TOC
        all_pdf_paths = [cover_pdf_path]
        # 2. General Cases Lists
        all_pdf_paths.extend(cases_table_pdfs)
        # 3. Construction Defects Lists
        all_pdf_paths.extend(defects_table_pdfs)
        # 4. Detail reports for cases
        all_pdf_paths.extend(cases_detail_pdfs)
        # 5. Detail reports for defects
        all_pdf_paths.extend(defects_detail_pdfs)

        for pdf_path in all_pdf_paths:
            reader = PdfReader(pdf_path)
            for page_obj in reader.pages:
                writer.add_page(page_obj)

        with open(output_pdf_path, "wb") as f_out:
            writer.write(f_out)

        print(f"\nSUCCESS: Export completed. File saved to: {output_pdf_path}")
        
    # Clean up temp folder
    try:
        shutil.rmtree(temp_dir)
        print("Cleaned up temporary print files.")
    except Exception as e:
        print(f"Warning: could not clean up temp files: {e}")

if __name__ == "__main__":
    main()
