import re
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "https://seicthdev.service-now.com"
STATE = "state.json"
OUT = Path("output")

# ปรับ URL list ให้ตรงกับของคุณ (ตัวอย่างเป็น change_request list)
CHANGE_LIST_URL = f"{BASE}/now/nav/ui/classic/params/target/change_request_list.do%3Fsysparm_query%3Dtype%3DCAB%5EORDERBYDESCsys_updated_on"

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

        # ServiceNow classic list มักอยู่ใน iframe: gsft_main
        # ถ้าไม่ใช่ classic ให้เอา frame logic ออก
        frame = page.frame(name="gsft_main") or page

        # รอให้ตารางมา
        frame.wait_for_selector("table.list_table", timeout=60_000)

        # ดึง link ของ change number ในหน้าปัจจุบัน
        # (ถ้าต้องการหลายหน้า ให้ทำ pagination เพิ่ม)
        rows = frame.locator("table.list_table tbody tr")
        count = rows.count()
        print(f"Found rows on page: {count}")

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
                frame.get_by_text("Export", exact=True).hover()
                with page.expect_download() as dl:
                    frame.get_by_text("PDF", exact=True).click()
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
            # ส่วนมากคือ attachments เหมือนกัน แต่ถ้าต้องคลิกทีละช่อง ก็ทำได้
            try:
                # คลิกแท็บ Supporting Documents
                tab = frame.get_by_role("tab", name="Supporting Documents")
                if tab.count() > 0:
                    tab.click()
                    frame.wait_for_timeout(800)

                    # ลองเก็บแบบ “Download All” อีกครั้ง ถ้าหน้านี้มี attachment section
                    # หรือคลิกแต่ละ “Click to add...” เพื่อดูไฟล์ที่แนบอยู่
                    links = [
                        "UAT SignOff File Attachment",
                        "App Scan File Attachment",
                        "CR File Attachment",
                    ]
                    for label in links:
                        # หาแถวที่มี label แล้วคลิกลิงก์ด้านขวา "Click to add..."
                        row = frame.locator(f"text={label}").first
                        if row.count() == 0:
                            continue

                        click_to_add = frame.get_by_text("Click to add...", exact=True).nth(0)
                        # หมายเหตุ: ถ้าในแท็บมีหลาย "Click to add..." ต้องทำ selector ให้ผูกกับ label (ค่อยปรับตอน debug)
                        # โค้ดนี้เป็น skeleton
            except Exception as e:
                print(f"[WARN] Supporting Documents handling skipped: {e}")

            # กลับไป list (ปุ่ม back ของ browser)
            page.go_back()
            frame = page.frame(name="gsft_main") or page
            frame.wait_for_selector("table.list_table", timeout=60_000)

        browser.close()

if __name__ == "__main__":
    main()