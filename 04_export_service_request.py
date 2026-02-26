import re
from pathlib import Path
from playwright.sync_api import sync_playwright

## DEV
# BASE = "https://seicthdev.service-now.com"

#PRD
BASE = "https://seicth.service-now.com/"

STATE = "state.json"
OUT = Path("output_ritm")
DOWNLOADED_LOG = Path("downloaded_ritm.log")  # Log file to track completed downloads

# URL สำหรับ Requested Items list
RITM_LIST_URL = (
    f"{BASE}/now/nav/ui/classic/params/target/"
    "sc_req_item_list.do%3Fsysparm_query%3Dactive%253Dtrue%255EEQ"
)

def safe_name(s: str) -> str:
    s = s.strip()
    s = re.sub(r'[\\/:*?"<>|]+', "_", s)
    return s[:150]

def wait_download(download, target: Path):
    target.parent.mkdir(parents=True, exist_ok=True)
    download.save_as(str(target))

def load_downloaded() -> set:
    """Load the set of already downloaded RITM numbers from log file"""
    if not DOWNLOADED_LOG.exists():
        return set()

    downloaded = set()
    with open(DOWNLOADED_LOG, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                downloaded.add(line)
    return downloaded

def mark_downloaded(ritm_number: str):
    """Mark a RITM number as downloaded by appending to log file"""
    with open(DOWNLOADED_LOG, 'a', encoding='utf-8') as f:
        f.write(f"{ritm_number}\n")
        f.flush()  # Ensure it's written immediately

def main():
    OUT.mkdir(parents=True, exist_ok=True)

    # Load already downloaded RITM numbers for resume capability
    downloaded = load_downloaded()
    if downloaded:
        print(f"Found {len(downloaded)} already downloaded RITM(s). Will skip them.")
    else:
        print("No previous downloads found. Starting fresh.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # ตอนแรกแนะนำ headless=False เพื่อ debug selector
        context = browser.new_context(storage_state=STATE, accept_downloads=True)
        page = context.new_page()

        # เข้า Requested Items list
        page.goto(RITM_LIST_URL, wait_until="domcontentloaded")

        # รอให้หน้าโหลดเสร็จ
        page.wait_for_timeout(3000)

        # ตรวจสอบว่า session หมดอายุหรือไม่ (ถูก redirect ไป login page)
        current_url = page.url.lower()
        if 'login' in current_url or 'sso' in current_url or 'auth' in current_url:
            print("[ERROR] Session expired! You need to login again.")
            print("Please run: python 01_login_save_state.py")
            page.screenshot(path="debug_session_expired.png")
            browser.close()
            return

        # ServiceNow classic list มักอยู่ใน iframe: gsft_main
        gsft_frame = page.frame(name="gsft_main")
        if gsft_frame:
            print("Found gsft_main iframe (Classic UI)")
            frame = gsft_frame
        else:
            print("No gsft_main iframe (Modern UI or direct page)")
            frame = page

        # รอให้ตารางมา
        print("Waiting for table to load...")
        try:
            frame.wait_for_selector("table.list_table, table[role='table'], div[role='grid']", timeout=60_000)
            print("Table found!")
        except Exception as e:
            print(f"[ERROR] Cannot find table. Current URL: {page.url}")
            print("Taking screenshot for debug...")
            page.screenshot(path="debug_ritm_list_page.png")
            print("\nPossible causes:")
            print("1. Session expired - run: python 01_login_save_state.py")
            print("2. Wrong URL or page structure changed")
            print("3. Page is still loading - check debug_ritm_list_page.png")
            browser.close()
            raise

        # ---------- กดปุ่ม "All" เพื่อแสดงทุกรายการ ----------
        try:
            print("Looking for 'All' filter option...")
            all_link = None

            # ลองหาหลาย selector สำหรับปุ่ม/ลิงก์ "All"
            selectors = [
                'a[onclick*="all"]:has-text("All")',
                'a.breadcrumb_link:has-text("All")',
                'a:has-text("All")',
                'span.breadcrumb_element a:has-text("All")',
                'button:has-text("All")',
            ]

            for sel in selectors:
                candidate = frame.locator(sel).first
                if candidate.count() > 0:
                    all_link = candidate
                    print(f"[DEBUG] Found 'All' with selector: {sel}")
                    break

            if all_link is None:
                # fallback: ลองหาใน page context
                for sel in selectors:
                    candidate = page.locator(sel).first
                    if candidate.count() > 0:
                        all_link = candidate
                        print(f"[DEBUG] Found 'All' in page context with selector: {sel}")
                        break

            if all_link is not None:
                all_link.click(timeout=5_000)
                print("Clicked 'All' - waiting for table to reload...")
                page.wait_for_timeout(3000)

                # Refresh frame reference หลังจาก reload
                frame = page.frame(name="gsft_main") or page

                # รอให้ตารางโหลดใหม่
                frame.wait_for_selector("table.list_table, table[role='table'], div[role='grid']", timeout=60_000)
                page.wait_for_timeout(1000)
                print("Table reloaded with all items!")
            else:
                print("[WARN] 'All' option not found - proceeding with current view")

        except Exception as e:
            print(f"[WARN] Could not click 'All' filter: {e}")
            print("Proceeding with current view...")

        # ---------- เปลี่ยนเป็น 100 rows per page ----------
        try:
            print("Setting page size to 100 rows per page...")

            # Step 1: หาและกดปุ่ม menu icon control button
            control_button = None

            # ลอง selector หลายแบบสำหรับปุ่ม control (Show menu)
            control_selectors = [
                'button#sc_req_item_control_button',
                'button[id*="control_button"]',
                'button[aria-label="Show"]',
                'button:has-text("Show")',
            ]

            for sel in control_selectors:
                candidate = frame.locator(sel).first
                if candidate.count() > 0:
                    control_button = candidate
                    print(f"[DEBUG] Found control button with selector: {sel}")
                    break

            if control_button is None:
                # fallback: ลองหาใน page context
                for sel in control_selectors:
                    candidate = page.locator(sel).first
                    if candidate.count() > 0:
                        control_button = candidate
                        print(f"[DEBUG] Found control button in page context with selector: {sel}")
                        break

            if control_button is not None:
                # คลิกปุ่ม control
                control_button.click()
                print("Clicked control button - waiting for context menu...")
                page.wait_for_timeout(1000)

                # Step 2: หาและคลิก "Show" submenu item
                show_menu_item = None

                # ลอง selector หลายแบบสำหรับ Show submenu
                show_selectors = [
                    'div.context_item[data-context-menu-label="Show"][role="menuitem"]',
                    'div.context_item[data-context-menu-label="Show"]',
                    'div.context_item:has-text("Show")[aria-haspopup="true"]',
                ]

                for sel in show_selectors:
                    candidate = frame.locator(sel).first
                    if candidate.count() > 0:
                        show_menu_item = candidate
                        print(f"[DEBUG] Found 'Show' menu item with selector: {sel}")
                        break

                if show_menu_item is None:
                    # ลองหาใน page context
                    for sel in show_selectors:
                        candidate = page.locator(sel).first
                        if candidate.count() > 0:
                            show_menu_item = candidate
                            print(f"[DEBUG] Found 'Show' menu item in page context with selector: {sel}")
                            break

                if show_menu_item is not None:
                    print("Clicking 'Show' submenu item...")
                    show_menu_item.click()
                    print("Show submenu clicked - waiting for submenu to appear...")
                    page.wait_for_timeout(2000)
                    print("Looking for '100 rows per page'...")
                else:
                    print("[WARN] Could not find 'Show' submenu item")

                # Step 3: หา context menu item "100 rows per page"
                # ลอง selector หลายแบบ โดยลองใน page context ก่อน (submenu มักจะ render ที่ page level)
                item_100 = None

                # ลอง selector หลายแบบ
                selectors_100 = [
                    'div.context_item[item_id="100"][role="menuitem"]',
                    'div.context_item[item_id="100"]',
                    'div.context_item[func_set="true"]:has-text("100 rows per page")',
                    'div.context_item:has-text("100 rows per page")',
                ]

                # ลองหาใน page context ก่อน
                for sel in selectors_100:
                    candidate = page.locator(sel).first
                    if candidate.count() > 0:
                        item_100 = candidate
                        print(f"[DEBUG] Found '100 rows per page' in page context with selector: {sel}")
                        break

                # ถ้าไม่เจอใน page context ลองใน frame
                if item_100 is None:
                    for sel in selectors_100:
                        candidate = frame.locator(sel).first
                        if candidate.count() > 0:
                            item_100 = candidate
                            print(f"[DEBUG] Found '100 rows per page' in frame context with selector: {sel}")
                            break

                if item_100 is not None and item_100.count() > 0:
                    print("[DEBUG] Clicking '100 rows per page' menu item...")
                    item_100.click()
                    print("Selected 100 rows per page - waiting for table to reload...")
                    page.wait_for_timeout(3000)

                    # Refresh frame reference หลังจาก reload
                    frame = page.frame(name="gsft_main") or page

                    # รอให้ตารางโหลดใหม่
                    frame.wait_for_selector("table.list_table, table[role='table'], div[role='grid']", timeout=60_000)
                    page.wait_for_timeout(1000)
                    print("Table reloaded with 100 rows per page!")
                else:
                    print("[WARN] Could not find '100 rows per page' menu item")
                    # ปิด menu ที่เปิดไว้
                    frame.keyboard.press("Escape")
                    page.wait_for_timeout(500)
            else:
                print("[WARN] Control button not found - trying JavaScript approach...")
                # ลองใช้ JavaScript หาและคลิก
                changed = frame.evaluate("""
                    () => {
                        // Step 1: หาปุ่ม control button โดยเฉพาะ
                        let controlBtn = document.querySelector('button#sc_req_item_control_button');
                        if (!controlBtn) {
                            controlBtn = document.querySelector('button[id*="control_button"]');
                        }
                        if (!controlBtn) {
                            // fallback: หาปุ่ม Show
                            const showButtons = document.querySelectorAll('button[aria-label="Show"], button');
                            for (const btn of showButtons) {
                                if (btn.textContent.includes('Show') || btn.getAttribute('aria-label') === 'Show') {
                                    controlBtn = btn;
                                    break;
                                }
                            }
                        }

                        if (controlBtn) {
                            controlBtn.click();

                            // Step 2: คลิก Show submenu item
                            setTimeout(() => {
                                const showSubmenu = document.querySelector('div.context_item[data-context-menu-label="Show"][role="menuitem"]');
                                if (showSubmenu) {
                                    showSubmenu.click();

                                    // Step 3: คลิก 100 rows per page
                                    setTimeout(() => {
                                        const item100 = document.querySelector('div.context_item[item_id="100"][role="menuitem"]');
                                        if (item100) {
                                            item100.click();
                                        }
                                    }, 500);
                                }
                            }, 500);

                            return true;
                        }
                        return false;
                    }
                """)

                if changed:
                    print("Clicked via JavaScript - waiting for reload...")
                    page.wait_for_timeout(3500)
                    frame = page.frame(name="gsft_main") or page
                    frame.wait_for_selector("table.list_table, table[role='table'], div[role='grid']", timeout=60_000)
                    page.wait_for_timeout(1000)
                    print("Table reloaded with 100 rows per page!")
                else:
                    print("[WARN] Could not change rows per page - proceeding with default (20 rows)")

        except Exception as e:
            print(f"[WARN] Could not change rows per page: {e}")
            print("Proceeding with default rows per page...")

        # Loop through all pages until no more next page button
        page_number = 1

        while True:
            print(f"\n===== Processing Page {page_number} =====")

            # ลองหา rows จากหลาย selector
            rows = frame.locator("table.list_table tbody tr, table[role='table'] tbody tr, div[role='row']")
            count = rows.count()
            print(f"Found {count} rows on page {page_number}")

            for i in range(count):
                row = rows.nth(i)

                # คลิกที่ RITM Number ลิงก์ตัวแรกในแถว
                link = row.locator("a.linked.formlink").first

                # เช็คว่ามี link หรือไม่ก่อน
                if link.count() == 0:
                    print(f"[WARN] No link found in row {i+1}, skipping")
                    continue

                # Scroll element into view และรอให้ stable ก่อนอ่าน
                try:
                    link.scroll_into_view_if_needed(timeout=5000)
                    frame.wait_for_timeout(300)  # รอให้ scroll เสร็จ
                except Exception as scroll_err:
                    print(f"[WARN] Could not scroll row {i+1} into view: {scroll_err}")
                    continue

                try:
                    # ใช้ timeout สั้นๆ 5 วินาที แทน 30 วินาที
                    number = link.inner_text(timeout=5000).strip()
                except Exception as e:
                    print(f"[WARN] Could not read RITM number for row {i+1}: {e}")
                    continue

                if not number:
                    print(f"[WARN] Empty RITM number in row {i+1}, skipping")
                    continue

                # Check if already downloaded (for resume capability)
                if number in downloaded:
                    print(f"\n=== {number} (Row {i+1}/{count}, Page {page_number}) === [SKIPPED - Already downloaded]")
                    continue

                folder = OUT / safe_name(number)
                folder.mkdir(parents=True, exist_ok=True)

                print(f"\n=== {number} (Row {i+1}/{count}, Page {page_number}) ===")

                # เปิด record ในแท็บเดิม
                link.click()

                # รายการแรกอาจจะต้องรอนานกว่า (session initialization)
                if i == 0 and page_number == 1:
                    print("First record - waiting extra time for page to stabilize...")
                    page.wait_for_timeout(5000)
                else:
                    page.wait_for_timeout(2000)

                # หลังคลิกเข้า record หน้า form มักอยู่ใน gsft_main เหมือนเดิม
                frame = page.frame(name="gsft_main") or page

                # รอ form มา
                try:
                    frame.wait_for_selector("form", timeout=60_000)
                except Exception as e:
                    print(f"[WARN] Form not found, trying to continue anyway. Error: {e}")
                    page.wait_for_timeout(3000)

                # ---------- (A) Export PDF ผ่าน UI ----------
                # Step 1-5: Additional actions -> Export -> PDF -> Export -> Download
                try:
                    # Step 1: กดปุ่ม "Additional actions" (icon menu)
                    additional_actions_btn = frame.locator('button.additional-actions-context-menu-button[aria-label="additional actions"]').first
                    if additional_actions_btn.count() == 0:
                        # ลองหาใน page หลัก (ไม่ใช่ใน frame)
                        additional_actions_btn = page.locator('button.additional-actions-context-menu-button[aria-label="additional actions"]').first

                    additional_actions_btn.click(timeout=5_000)
                    print("Clicked Additional actions button")

                    # รอให้เมนูแสดงและ stable
                    frame.wait_for_timeout(2000)  # เพิ่มเวลารอให้มากขึ้น

                    # Step 2: รอให้ Export menu แสดงก่อนที่จะ hover
                    export_menu = None
                    for attempt in range(3):  # ลอง 3 ครั้ง
                        try:
                            # ลองหา Export menu item ทั้งใน frame และ page context
                            export_menu = frame.locator('div.context_item[role="menuitem"][data-context-menu-label="Export"]').first
                            if export_menu.count() == 0:
                                # fallback 1: ลองหาด้วย item_id ใน frame
                                export_menu = frame.locator('div.context_item[item_id="context_exportmenu"]').first

                            if export_menu.count() == 0:
                                # fallback 2: ลองหาใน page context
                                export_menu = page.locator('div.context_item[role="menuitem"][data-context-menu-label="Export"]').first

                            if export_menu.count() == 0:
                                # fallback 3: ลองหาด้วย item_id ใน page context
                                export_menu = page.locator('div.context_item[item_id="context_exportmenu"]').first

                            if export_menu.count() > 0:
                                # รอให้ visible
                                export_menu.wait_for(state="visible", timeout=5_000)
                                print(f"[DEBUG] Found Export menu (attempt {attempt+1})")
                                break
                            else:
                                if attempt < 2:
                                    print(f"Export menu not found, retrying... (attempt {attempt+1}/3)")
                                    frame.wait_for_timeout(1500)  # เพิ่มเวลารอระหว่าง retry
                        except Exception as e:
                            if attempt < 2:
                                print(f"Error waiting for Export menu, retrying... (attempt {attempt+1}/3): {e}")
                                frame.wait_for_timeout(1500)
                            else:
                                raise

                    if export_menu is None or export_menu.count() == 0:
                        raise Exception("Export menu not found after 3 attempts")

                    export_menu.hover()
                    frame.wait_for_timeout(500)  # รอให้ submenu แสดง

                    # Step 3: คลิก "PDF" item
                    pdf_item = frame.locator('div.context_item[role="menuitem"]:has-text("PDF")').first
                    pdf_item.click()
                    frame.wait_for_timeout(1000)  # รอให้ Export dialog ขึ้นมา

                    # Step 4: กดปุ่ม "Export" ใน dialog เพื่อเริ่ม generate PDF
                    export_btn = frame.locator('button#ok_button').first
                    if export_btn.count() == 0:
                        export_btn = page.locator('button#ok_button').first

                    export_btn.click()
                    print("Generating PDF...")

                    # รอให้ PDF generation เสร็จ และปุ่ม Download ปรากฏ
                    frame.wait_for_timeout(3000)  # รอให้ process PDF

                    # Step 5: กดปุ่ม "Download" เพื่อดาวน์โหลด PDF
                    download_btn = frame.locator('button#download_button').first
                    if download_btn.count() == 0:
                        download_btn = page.locator('button#download_button').first

                    # รอให้ปุ่ม Download พร้อม
                    download_btn.wait_for(state="visible", timeout=30_000)

                    with page.expect_download() as dl:
                        download_btn.click()
                    download = dl.value
                    wait_download(download, folder / f"{safe_name(number)}.pdf")
                    print("PDF saved")
                except Exception as e:
                    print(f"[WARN] Export PDF failed: {e}")

                # ---------- (B) Download All Attachments ----------
                try:
                    # คลิกปุ่ม paperclip icon (Manage Attachments)
                    paperclip_btn = frame.locator('button#header_add_attachment').first
                    if paperclip_btn.count() == 0:
                        # fallback: หาด้วย class และ aria-label
                        paperclip_btn = frame.locator('button.icon-paperclip[aria-label="Manage Attachments"]').first

                    if paperclip_btn.count() == 0:
                        # ลองหาใน page หลัก
                        paperclip_btn = page.locator('button#header_add_attachment').first

                    if paperclip_btn.count() > 0:
                        paperclip_btn.click()
                        print("Clicked Manage Attachments button")

                        # รอให้ Attachments dialog popup ขึ้นมา
                        frame.wait_for_timeout(2000)

                        # หาปุ่ม Download All โดยตรง
                        print("[DEBUG] Looking for Download All button...")

                        # ลองหาใน page หลักก่อน (modal อาจจะอยู่นอก frame)
                        download_all_btn = page.locator('input#download_all_button').first
                        if download_all_btn.count() > 0:
                            print("[DEBUG] Found Download All button in page context")
                        else:
                            # ลองหาใน frame
                            download_all_btn = frame.locator('input#download_all_button').first
                            if download_all_btn.count() > 0:
                                print("[DEBUG] Found Download All button in frame context")

                        if download_all_btn.count() == 0:
                            # fallback: หาด้วย onclick
                            download_all_btn = page.locator('input[onclick*="downloadAllAttachments"]').first
                            if download_all_btn.count() > 0:
                                print("[DEBUG] Found Download All button by onclick attribute")

                        if download_all_btn.count() > 0:
                            # สร้างโฟลเดอร์ Attachment
                            attachment_folder = folder / "Attachment"
                            attachment_folder.mkdir(parents=True, exist_ok=True)

                            print("Downloading all attachments...")

                            # ลอง JavaScript click ก่อน (เพราะปุ่มอาจไม่ visible)
                            try:
                                # เช็คว่า JavaScript หาปุ่มเจอหรือไม่
                                btn_found = page.evaluate("""
                                    () => {
                                        const btn = document.getElementById('download_all_button');
                                        return btn !== null;
                                    }
                                """)

                                if btn_found:
                                    print("[DEBUG] JavaScript found button, clicking...")
                                    with page.expect_download() as dl:
                                        page.evaluate("document.getElementById('download_all_button').click()")
                                    download_file = dl.value
                                    wait_download(download_file, attachment_folder / "attachments_all.zip")
                                    print("Attachments downloaded")
                                else:
                                    # JavaScript ไม่เจอ ลอง Playwright force click
                                    print("[DEBUG] JavaScript didn't find button, trying Playwright force click...")
                                    with page.expect_download() as dl:
                                        download_all_btn.click(force=True, timeout=10_000)
                                    download_file = dl.value
                                    wait_download(download_file, attachment_folder / "attachments_all.zip")
                                    print("Attachments downloaded")

                            except Exception as e:
                                print(f"[WARN] Could not download attachments: {e}")

                            # ปิด dialog ด้วยปุ่ม Close
                            print("[DEBUG] Closing Attachments dialog...")
                            try:
                                close_btn = page.locator('button#attachment_closemodal').first
                                if close_btn.count() == 0:
                                    close_btn = frame.locator('button#attachment_closemodal').first
                                if close_btn.count() > 0:
                                    print("[DEBUG] Found close button, clicking...")
                                    close_btn.click()
                                    print("[DEBUG] Dialog closed successfully")
                                else:
                                    # fallback: ใช้ ESC ถ้าหาปุ่มไม่เจอ
                                    print("[DEBUG] Close button not found, using Escape key...")
                                    frame.keyboard.press("Escape")
                                frame.wait_for_timeout(500)
                            except Exception as close_err:
                                print(f"[WARN] Error closing dialog: {close_err}")
                                # Try one more time with page keyboard
                                try:
                                    page.keyboard.press("Escape")
                                    frame.wait_for_timeout(500)
                                except:
                                    print("[WARN] Could not close dialog with Escape either")
                        else:
                            print("[INFO] No attachments or Download All button not found - closing dialog")
                            # ปิด dialog ด้วยปุ่ม Close
                            try:
                                close_btn = page.locator('button#attachment_closemodal').first
                                if close_btn.count() == 0:
                                    close_btn = frame.locator('button#attachment_closemodal').first
                                if close_btn.count() > 0:
                                    print("[DEBUG] Found close button, clicking...")
                                    close_btn.click()
                                else:
                                    # fallback: ใช้ ESC ถ้าหาปุ่มไม่เจอ
                                    print("[DEBUG] Close button not found, using Escape key...")
                                    frame.keyboard.press("Escape")
                                frame.wait_for_timeout(500)
                            except Exception as close_err:
                                print(f"[WARN] Error closing dialog: {close_err}")
                                try:
                                    page.keyboard.press("Escape")
                                    frame.wait_for_timeout(500)
                                except:
                                    print("[WARN] Could not close dialog with Escape either")
                    else:
                        print("[INFO] No attachments button found (may not have attachments)")

                except Exception as e:
                    print(f"[WARN] Attachments download failed: {e}")

                # Mark this RITM as downloaded (for resume capability)
                mark_downloaded(number)
                print(f"✓ {number} completed and logged")

                # กลับไป list (ปุ่ม back ของ browser)
                try:
                    print("[DEBUG] Going back to list...")
                    page.go_back()
                    print("[DEBUG] Verifying page is still valid...")
                    # Verify page is still valid
                    if page.is_closed():
                        print("[ERROR] Page was closed unexpectedly!")
                        break

                    frame = page.frame(name="gsft_main") or page
                    print("[DEBUG] Waiting for table to reappear...")
                    # รอให้กลับไปหน้า list
                    frame.wait_for_selector("table.list_table, table[role='table'], div[role='grid']", timeout=60_000)
                    page.wait_for_timeout(1000)  # รอให้ตารางโหลดเสร็จ
                    print("[DEBUG] Back to list successfully")
                except Exception as e:
                    print(f"[ERROR] Failed to return to list: {e}")
                    print("[ERROR] Browser/page may have been closed. Stopping.")
                    break

            # หลังจากประมวลผลทุก row ในหน้านี้แล้ว ตรวจสอบว่ามีปุ่ม Next Page หรือไม่
            print(f"\nCompleted page {page_number}. Checking for next page...")

            # Scroll หน้าลงไปล่างสุดก่อน เพื่อให้ pagination buttons เข้ามาในมุมมอง
            try:
                frame.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(500)
            except:
                pass

            # ใช้ JavaScript หาและ click ปุ่ม Next เพราะ Playwright click อาจถูกบัง
            try:
                result = frame.evaluate("""
                    () => {
                        // หาปุ่ม Next โดยใช้ name attribute
                        const btn = document.querySelector('button[name="vcr_next"]');
                        if (!btn) {
                            return { found: false, reason: 'button not found' };
                        }

                        // ตรวจสอบว่า disabled หรือไม่
                        if (btn.disabled) {
                            return { found: true, disabled: true };
                        }

                        // Click ด้วย JavaScript
                        btn.click();
                        return { found: true, disabled: false, clicked: true };
                    }
                """)

                print(f"Next Page button check: {result}")

                if not result.get('found'):
                    print("No Next Page button found. Reached last page.")
                    break
                elif result.get('disabled'):
                    print("Next Page button is disabled. Reached last page.")
                    break
                elif result.get('clicked'):
                    print("Successfully clicked Next Page button with JavaScript")

                    # รอให้หน้าใหม่โหลด
                    page.wait_for_timeout(3000)

                    # รอให้ตารางมา
                    frame.wait_for_selector("table.list_table, table[role='table'], div[role='grid']", timeout=60_000)
                    page.wait_for_timeout(1000)

                    page_number += 1
                    continue  # วนต่อไปยังหน้าถัดไป
                else:
                    print("[WARN] Unexpected result from Next Page button click")
                    break

            except Exception as e:
                print(f"[WARN] Failed to click Next Page with JavaScript: {e}")
                break

        print(f"\n===== Completed! Processed {page_number} page(s) =====")
        browser.close()

if __name__ == "__main__":
    main()
