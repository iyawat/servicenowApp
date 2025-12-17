from playwright.sync_api import sync_playwright
from pathlib import Path

## DEV
BASE = "https://seicthdev.service-now.com"

#PRD
# BASE = "https://seicth.service-now.com/"

STATE = Path("state.json")

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # เห็นหน้าจอเพื่อทำ SSO/MFA
        context = browser.new_context()
        page = context.new_page()

        page.goto(BASE, wait_until="domcontentloaded")

        # กดปุ่ม "Login with SSO" ถ้ามี (บาง instance redirect ไปหน้า SAML โดยตรง)
        try:
            login_sso_btn = page.locator('text="Login with SSO"').first
            if login_sso_btn.count() > 0:
                print("Found 'Login with SSO' button, clicking...")
                login_sso_btn.click(timeout=5_000)
                page.wait_for_timeout(2000)
            else:
                print("No 'Login with SSO' button - already on SSO/SAML login page")
        except Exception as e:
            print(f"Could not click 'Login with SSO' - might already be on SSO/SAML login page")
            print(f"Error: {e}")

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