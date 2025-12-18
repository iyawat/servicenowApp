# ติดตั้ง

1. สร้าง venv + ติดตั้ง
   python3 -m venv .venv
   source .venv/bin/activate

python3 -m pip install --upgrade pip
python3 -m pip install playwright
python3 -m playwright install

2. รัน login script
   python3 01_login_save_state.py

3. รัน Export Script
   python3 02_export_changes.py

4. รัน Report Script
   python3 03_check_file.py
