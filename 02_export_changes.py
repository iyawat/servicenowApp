import re
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "https://seicthdev.service-now.com"
STATE = "state.json"
OUT = Path("output")

# ปรับ URL list ให้ตรงกับของคุณ (ตัวอย่างเป็น change_request list)
CHANGE_LIST_URL = (
    f"{BASE}/now/nav/ui/classic/params/target/"
    "change_request_list.do?sysparm_view=cab"
)

def safe_name(s: str) -> str:
    s = s.strip()
    s = re.sub(r'[\\/:*?"<>|]+', "_", s)
    return s[:150]

def wait_download(download, target: Path):
    target.parent.mkdir(parents=True, exist_ok=True)
    download.save_as(str(target))

def main():
    OUT.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # ตอนแรกแนะนำ headless=False เพื่อ debug selector
        context = browser.new_context(storage_state=STATE, accept_downloads=True)
        page = context.new_page()

        # เข้า list
        page.goto(CHANGE_LIST_URL, wait_until="domcontentloaded")

        # รอให้หน้าโหลดเสร็จ
        page.wait_for_timeout(3000)

        # ServiceNow classic list มักอยู่ใน iframe: gsft_main
        # ถ้าไม่ใช่ classic ให้เอา frame logic ออก
        gsft_frame = page.frame(name="gsft_main")
        if gsft_frame:
            print("Found gsft_main iframe (Classic UI)")
            frame = gsft_frame
        else:
            print("No gsft_main iframe (Modern UI or direct page)")
            frame = page

        # รอให้ตารางมา - ลองหลาย selector
        print("Waiting for table to load...")
        try:
            # ลอง selector หลายแบบ
            frame.wait_for_selector("table.list_table, table[role='table'], div[role='grid']", timeout=60_000)
            print("Table found!")
        except Exception as e:
            print(f"[ERROR] Cannot find table. Current URL: {page.url}")
            print("Taking screenshot for debug...")
            page.screenshot(path="debug_list_page.png")
            raise

        # ดึง link ของ change number ในหน้าปัจจุบัน
        # (ถ้าต้องการหลายหน้า ให้ทำ pagination เพิ่ม)
        # ลองหา rows จากหลาย selector
        rows = frame.locator("table.list_table tbody tr, table[role='table'] tbody tr, div[role='row']")
        count = rows.count()
        print(f"Found {count} rows on page")

        for i in range(count):
            row = rows.nth(i)

            # คลิกที่ Change Number ลิงก์ตัวแรกในแถว
            link = row.locator("a.linked.formlink").first
            number = link.inner_text().strip()
            if not number:
                continue

            folder = OUT / safe_name(number)
            folder.mkdir(parents=True, exist_ok=True)

            print(f"\n=== {number} ===")

            # เปิด record ในแท็บเดิม
            link.click()
            # หลังคลิกเข้า record หน้า form มักอยู่ใน gsft_main เหมือนเดิม
            frame = page.frame(name="gsft_main") or page

            # รอ form มา
            frame.wait_for_selector("form", timeout=60_000)

            # ---------- (A) Export PDF ผ่าน UI ----------
            # จากรูป: เมนู 3 จุด/เมนู context แล้วมี Export > PDF
            # ใน UI แต่ละ instance ปุ่มอาจต่างกัน ต้องปรับ selector ให้ตรง
            try:
                # เปิดเมนู (มักเป็นปุ่มที่มี label "More options" หรือไอคอนสามจุด)
                # ลอง 2 แบบ: ปุ่ม "..." หรือ icon menu บน header
                menu_btn = frame.locator('button[aria-label*="More"]').first
                if menu_btn.count() == 0:
                    menu_btn = frame.locator("button:has-text('...')").first
                if menu_btn.count() == 0:
                    # บางทีเป็นไอคอนใน header (ไม่อยู่ใน frame)
                    menu_btn = page.locator('button[aria-label*="More"]').first

                menu_btn.click(timeout=5_000)

                # hover/click Export -> PDF
                # ใช้ selector ตาม element จริง: div.context_item[role="menuitem"]
                export_menu = frame.locator('div.context_item[role="menuitem"]:has-text("Export")').first
                export_menu.hover()
                frame.wait_for_timeout(500)  # รอให้ submenu แสดง

                # คลิก PDF item
                pdf_item = frame.locator('div.context_item[role="menuitem"]:has-text("PDF")').first
                pdf_item.click()

                # รอให้ Export dialog ขึ้นมา และกดปุ่ม Export เพื่อยืนยัน
                frame.wait_for_timeout(1000)
                export_btn = frame.locator('button#ok_button:has-text("Export")').first

                with page.expect_download() as dl:
                    export_btn.click()
                download = dl.value
                wait_download(download, folder / f"{safe_name(number)}.pdf")
                print("PDF saved")
            except Exception as e:
                print(f"[WARN] Export PDF failed: {e}")

            # ---------- (B) Download attachments จาก paperclip ----------
            # ถ้ากด paperclip แล้วมีปุ่ม Download All ให้ใช้เลย
            try:
                # บาง UI paperclip เป็นไอคอนบน form header
                clip = frame.locator('button[aria-label*="Attachment"], a[aria-label*="Attachment"]').first
                if clip.count() == 0:
                    clip = frame.locator("span.icon-paperclip").first

                if clip.count() > 0:
                    clip.click()

                    # modal attachments
                    # รอให้ปุ่ม Download All โผล่
                    frame.wait_for_timeout(1000)

                    # ถ้า Download All เป็น “download” ไฟล์เดียว (zip) จะจับด้วย expect_download
                    dlall = frame.get_by_text("Download All")
                    if dlall.count() > 0:
                        with page.expect_download() as dl2:
                            dlall.click()
                        download2 = dl2.value
                        wait_download(download2, folder / "attachments_download_all.zip")
                        print("Attachments Download All saved")
            except Exception as e:
                print(f"[WARN] Paperclip download failed: {e}")

            # ---------- (C) Supporting Documents tab ----------
            # ในรูปมี UAT SignOff / App Scan / CR File Attachment (เป็น link Click to add...)
            # ดาวน์โหลดไฟล์แนบจากแต่ละ field ใน Supporting Documents
            try:
                # คลิกแท็บ Supporting Documents
                tab = frame.get_by_role("tab", name="Supporting Documents")
                if tab.count() > 0:
                    tab.click()
                    frame.wait_for_timeout(1500)
                    print("Opened Supporting Documents tab")

                    # รายการ field attachments ที่ต้องการดาวน์โหลด
                    attachment_fields = [
                        ("UAT SignOff File Attachment", "uat_signoff"),
                        ("App Scan File Attachment", "app_scan"),
                        ("CR File Attachment", "cr_file"),
                    ]

                    for label, folder_name in attachment_fields:
                        try:
                            # หา label row
                            label_elem = frame.locator(f"text={label}").first
                            if label_elem.count() == 0:
                                continue

                            # หาช่อง attachment ที่อยู่ติดกับ label (มักเป็น sibling หรือ parent row)
                            # วิธีที่ 1: ลองหาปุ่ม paperclip หรือ attachment link ในบริเวณเดียวกับ label
                            # วิธีที่ 2: หา "Click to add..." link ถ้ามีไฟล์แนบแล้วจะเป็น link ที่แสดงจำนวนไฟล์

                            # หา parent row ของ label
                            parent_row = label_elem.locator("xpath=ancestor::tr[1]")

                            # ลองหา paperclip icon หรือ attachment link ในแถวนี้
                            attachment_links = parent_row.locator("a[aria-label*='Attachment'], span.icon-paperclip, a:has-text('attachment')").all()

                            # หรือลองหาปุ่มที่แสดงจำนวนไฟล์ เช่น "2 attachments"
                            attachment_count_links = parent_row.locator("a.list_edit_attachment").all()

                            if len(attachment_count_links) > 0:
                                # มีไฟล์แนบ - คลิกเพื่อเปิด attachment modal
                                print(f"  Found attachments in {label}")
                                attachment_count_links[0].click()
                                frame.wait_for_timeout(1000)

                                # สร้างโฟลเดอร์ย่อยสำหรับ field นี้
                                field_folder = folder / "supporting_documents" / folder_name
                                field_folder.mkdir(parents=True, exist_ok=True)

                                # ดาวน์โหลดไฟล์ทั้งหมดจาก modal
                                # วิธีที่ 1: ลองหาปุ่ม "Download All"
                                download_all_btn = frame.locator("button:has-text('Download All'), a:has-text('Download All')").first
                                if download_all_btn.count() > 0:
                                    with page.expect_download() as dl:
                                        download_all_btn.click()
                                    download = dl.value
                                    wait_download(download, field_folder / f"{folder_name}_all.zip")
                                    print(f"    Downloaded all files from {label}")
                                else:
                                    # วิธีที่ 2: ดาวน์โหลดทีละไฟล์
                                    file_links = frame.locator("a[href*='sys_attachment']").all()
                                    for idx, file_link in enumerate(file_links):
                                        try:
                                            filename = file_link.inner_text().strip()
                                            if filename:
                                                with page.expect_download() as dl:
                                                    file_link.click()
                                                download = dl.value
                                                wait_download(download, field_folder / safe_name(filename))
                                                print(f"    Downloaded: {filename}")
                                        except Exception as e:
                                            print(f"    [WARN] Failed to download file {idx}: {e}")

                                # ปิด modal (กด ESC หรือหาปุ่ม close)
                                page.keyboard.press("Escape")
                                frame.wait_for_timeout(500)

                            elif len(attachment_links) > 0:
                                # มี paperclip icon - คลิกเพื่อเปิด
                                print(f"  Found attachment icon in {label}")
                                attachment_links[0].click()
                                frame.wait_for_timeout(1000)

                                # ทำการดาวน์โหลดเหมือนข้างบน
                                field_folder = folder / "supporting_documents" / folder_name
                                field_folder.mkdir(parents=True, exist_ok=True)

                                download_all_btn = frame.locator("button:has-text('Download All'), a:has-text('Download All')").first
                                if download_all_btn.count() > 0:
                                    with page.expect_download() as dl:
                                        download_all_btn.click()
                                    download = dl.value
                                    wait_download(download, field_folder / f"{folder_name}_all.zip")
                                    print(f"    Downloaded all files from {label}")

                                page.keyboard.press("Escape")
                                frame.wait_for_timeout(500)
                            else:
                                print(f"  No attachments found for {label}")

                        except Exception as e:
                            print(f"  [WARN] Failed to process {label}: {e}")

                    # กลับไปแท็บแรก (optional)
                    # main_tab = frame.get_by_role("tab", name="Planning")
                    # if main_tab.count() > 0:
                    #     main_tab.click()

            except Exception as e:
                print(f"[WARN] Supporting Documents handling skipped: {e}")

            # กลับไป list (ปุ่ม back ของ browser)
            page.go_back()
            frame = page.frame(name="gsft_main") or page
            # รอให้กลับไปหน้า list
            frame.wait_for_selector("table.list_table, table[role='table'], div[role='grid']", timeout=60_000)
            page.wait_for_timeout(1000)  # รอให้ตารางโหลดเสร็จ

        browser.close()

if __name__ == "__main__":
    main()