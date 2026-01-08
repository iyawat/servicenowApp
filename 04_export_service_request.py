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
    "sc_req_item_list.do?sysparm_query=active%3Dtrue%5EEQ"
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
            raise

        # Loop through all pages until no more next page button
        page_number = 1

        while True:
            print(f"\n===== Processing Page {page_number} =====")

            # ลองหา rows จากหลาย selector
            rows = frame.locator("table.list_table tbody tr, table[role='table'] tbody tr, div[role='row']")
            count = rows.count()
            print(f"Found {count} rows on page {page_number}")

            for i in range(count):
                # Re-fetch rows each time to avoid stale element after go_back
                rows = frame.locator("table.list_table tbody tr, table[role='table'] tbody tr, div[role='row']")
                row = rows.nth(i)

                # คลิกที่ RITM Number ลิงก์ตัวแรกในแถว - retry if stale
                number = None
                for attempt in range(3):
                    try:
                        link = row.locator("a.linked.formlink").first
                        number = link.inner_text(timeout=10_000).strip()
                        if number:
                            break
                    except Exception as e:
                        if attempt < 2:
                            print(f"[WARN] Failed to get RITM number (attempt {attempt+1}/3): {e}")
                            frame.wait_for_timeout(1000)
                            # Re-fetch row
                            rows = frame.locator("table.list_table tbody tr, table[role='table'] tbody tr, div[role='row']")
                            row = rows.nth(i)
                        else:
                            raise

                if not number:
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
                # Step 1-5: Hamburger menu -> Export -> PDF -> Export -> Download
                try:
                    # Step 1: กดปุ่ม hamburger menu (สำหรับ RITM)
                    print("[DEBUG] Looking for hamburger menu button...")

                    # Take screenshot for debugging
                    if i == 0 and page_number == 1:
                        page.screenshot(path=f"debug_ritm_form_{number}.png")
                        print(f"[DEBUG] Saved screenshot to debug_ritm_form_{number}.png")

                    # ใช้ปุ่ม "Additional actions" ที่ถูกต้อง
                    # Element: <button class="additional-actions-context-menu-button" aria-label="additional actions">
                    additional_actions_btn = None

                    # ลองหาด้วย class name (specific)
                    additional_actions_btn = frame.locator('button.additional-actions-context-menu-button').first
                    if additional_actions_btn.count() == 0:
                        additional_actions_btn = page.locator('button.additional-actions-context-menu-button').first

                    # ลองหาด้วย aria-label
                    if additional_actions_btn.count() == 0:
                        additional_actions_btn = frame.locator('button[aria-label="additional actions"]').first
                    if additional_actions_btn.count() == 0:
                        additional_actions_btn = page.locator('button[aria-label="additional actions"]').first

                    # ลองหาด้วย onclick attribute
                    if additional_actions_btn.count() == 0:
                        additional_actions_btn = frame.locator('button[onclick*="contextShow"]').first
                    if additional_actions_btn.count() == 0:
                        additional_actions_btn = page.locator('button[onclick*="contextShow"]').first

                    if additional_actions_btn.count() > 0:
                        additional_actions_btn.click(timeout=5_000)
                        print("Clicked Additional actions button")
                    else:
                        raise Exception("Additional actions button not found")

                    # รอให้เมนูแสดงและ stable
                    page.wait_for_timeout(1000)

                    # Step 2-3: หาและคลิก PDF menu item โดยตรง
                    # ตอนนี้ menu เปิดอยู่แล้ว ไม่ต้อง hover Export อีก
                    print("[DEBUG] Looking for PDF menu item...")

                    # ลองหา PDF item ด้วย JavaScript ก่อน (เร็วกว่า)
                    pdf_clicked = frame.evaluate("""
                        () => {
                            // หา PDF menu item
                            const menuItems = document.querySelectorAll('div.context_item[role="menuitem"], div[role="menuitem"]');

                            for (let item of menuItems) {
                                const text = item.innerText || item.textContent || '';
                                if (text.trim() === 'PDF') {
                                    item.click();
                                    return { success: true, text: text };
                                }
                            }

                            return { success: false };
                        }
                    """)

                    if pdf_clicked.get('success'):
                        print("[DEBUG] Clicked PDF with JavaScript")
                    else:
                        # Fallback: ใช้ Playwright
                        print("[DEBUG] Trying Playwright selectors for PDF...")
                        pdf_item = page.locator('div.context_item[role="menuitem"]:has-text("PDF")').first
                        if pdf_item.count() == 0:
                            pdf_item = frame.locator('div.context_item[role="menuitem"]:has-text("PDF")').first
                        if pdf_item.count() == 0:
                            pdf_item = page.locator('div[role="menuitem"]:has-text("PDF")').first
                        if pdf_item.count() == 0:
                            pdf_item = frame.locator('div[role="menuitem"]:has-text("PDF")').first

                        if pdf_item.count() > 0:
                            pdf_item.click()
                            print("Clicked PDF menu item with Playwright")
                        else:
                            raise Exception("PDF menu item not found")

                    page.wait_for_timeout(1000)  # รอให้ Export dialog ขึ้นมา

                    # Step 4: กดปุ่ม "Export" ใน dialog เพื่อเริ่ม generate PDF
                    # Dialogs usually appear in page context (outside iframe)
                    export_btn = page.locator('button#ok_button').first
                    if export_btn.count() == 0:
                        export_btn = frame.locator('button#ok_button').first

                    export_btn.click()
                    print("Generating PDF...")

                    # รอให้ PDF generation เสร็จ และปุ่ม Download ปรากฏ
                    page.wait_for_timeout(5000)  # เพิ่มเวลารอให้ PDF process เสร็จ

                    # Step 5: กดปุ่ม "Download" เพื่อดาวน์โหลด PDF
                    download_btn = page.locator('button#download_button').first
                    if download_btn.count() == 0:
                        download_btn = frame.locator('button#download_button').first

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
                            close_btn = page.locator('button#attachment_closemodal').first
                            if close_btn.count() == 0:
                                close_btn = frame.locator('button#attachment_closemodal').first
                            if close_btn.count() > 0:
                                close_btn.click()
                            else:
                                # fallback: ใช้ ESC ถ้าหาปุ่มไม่เจอ
                                page.keyboard.press("Escape")
                            frame.wait_for_timeout(500)
                        else:
                            print("[INFO] No attachments or Download All button not found - closing dialog")
                            # ปิด dialog ด้วยปุ่ม Close
                            close_btn = page.locator('button#attachment_closemodal').first
                            if close_btn.count() == 0:
                                close_btn = frame.locator('button#attachment_closemodal').first
                            if close_btn.count() > 0:
                                close_btn.click()
                            else:
                                # fallback: ใช้ ESC ถ้าหาปุ่มไม่เจอ
                                page.keyboard.press("Escape")
                            frame.wait_for_timeout(500)
                    else:
                        print("[INFO] No attachments button found (may not have attachments)")

                except Exception as e:
                    print(f"[WARN] Attachments download failed: {e}")

                # Mark this RITM as downloaded (for resume capability)
                mark_downloaded(number)
                print(f"✓ {number} completed and logged")

                # กลับไป list (ปุ่ม back ของ browser)
                page.go_back()
                frame = page.frame(name="gsft_main") or page
                # รอให้กลับไปหน้า list
                frame.wait_for_selector("table.list_table, table[role='table'], div[role='grid']", timeout=60_000)
                page.wait_for_timeout(1000)  # รอให้ตารางโหลดเสร็จ

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
