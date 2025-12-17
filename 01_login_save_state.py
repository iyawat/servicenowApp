from playwright.sync_api import sync_playwright
from pathlib import Path

BASE = "https://seicthdev.service-now.com"
STATE = Path("state.json")

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # เห็นหน้าจอเพื่อทำ SSO/MFA
        context = browser.new_context()
        page = context.new_page()

        page.goto(BASE, wait_until="domcontentloaded")

        # กดปุ่ม "Login with SSO" (ตามหน้าจอที่คุณส่งมา)
        page.get_by_text("Login with SSO", exact=True).click()

        print("\n[Action Required]")
        print("ทำ SSO login + MFA ให้เสร็จในหน้าต่าง browser ที่เปิดอยู่")
        print("แล้วไปหน้า ServiceNow ที่เข้าระบบได้ (เห็น navigator/top bar)")

        # รอจนกว่าจะ login สำเร็จ (คุณอาจปรับ condition ให้เข้ากับ instance)
        page.wait_for_timeout(2000)
        page.wait_for_url("**/now/**", timeout=10 * 60 * 1000)  # รอนานสุด 10 นาทีให้ทำ MFA

        context.storage_state(path=str(STATE))
        print(f"\n✅ Saved session state to: {STATE.resolve()}")

        browser.close()

if __name__ == "__main__":
    main()