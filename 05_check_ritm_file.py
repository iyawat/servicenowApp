#!/usr/bin/env python3
"""
05_check_ritm_file.py

ตรวจสอบความสมบูรณ์ของไฟล์ RITM ที่ดาวน์โหลดจาก ServiceNow
และสร้างรายงาน

การใช้งาน:
    python 05_check_ritm_file.py
"""

import csv
import re
from pathlib import Path
from datetime import datetime

# Configuration
OUTPUT_DIR = Path("output_ritm")
DOWNLOADED_LOG = Path("downloaded_ritm.log")
REPORT_FILE = Path("ritm_file_check_report.csv")

def safe_name(s: str) -> str:
    """Same sanitization as export script"""
    s = s.strip()
    s = re.sub(r'[\\/:*?"<>|]+', "_", s)
    return s[:150]

def load_downloaded() -> set:
    """Load the set of downloaded RITM numbers from log file"""
    if not DOWNLOADED_LOG.exists():
        return set()

    downloaded = set()
    with open(DOWNLOADED_LOG, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                downloaded.add(line)
    return downloaded

def check_ritm_folder(ritm_number: str) -> dict:
    """
    ตรวจสอบความสมบูรณ์ของไฟล์ใน RITM folder

    Returns:
        dict: สถานะของไฟล์แต่ละประเภท
    """
    folder = OUTPUT_DIR / safe_name(ritm_number)

    result = {
        'ritm_number': ritm_number,
        'folder_exists': 'No',
        'pdf': 'No',
        'pdf_size_kb': 0,
        'attachments': 'No',
        'attachment_count': 0,
        'attachment_files': [],
        'status': 'Missing',
        'notes': []
    }

    # ตรวจสอบว่าโฟลเดอร์มีหรือไม่
    if not folder.exists():
        result['status'] = 'Folder Missing'
        result['notes'].append('Folder does not exist')
        return result

    result['folder_exists'] = 'Yes'

    # ตรวจสอบ PDF
    pdf_file = folder / f"{safe_name(ritm_number)}.pdf"
    if pdf_file.exists() and pdf_file.is_file():
        result['pdf'] = 'Yes'
        result['pdf_size_kb'] = pdf_file.stat().st_size / 1024
        result['notes'].append(f"PDF: {result['pdf_size_kb']:.1f} KB")

    # ตรวจสอบ Attachments
    attachment_folder = folder / "Attachment"
    if attachment_folder.exists() and attachment_folder.is_dir():
        attachment_files = [f for f in attachment_folder.glob("*") if f.is_file()]
        if attachment_files:
            result['attachments'] = 'Yes'
            result['attachment_count'] = len(attachment_files)
            result['attachment_files'] = [f.name for f in attachment_files]
            
            total_size = sum(f.stat().st_size for f in attachment_files)
            result['notes'].append(f"Attachments: {len(attachment_files)} file(s), {total_size/1024:.1f} KB")

    # กำหนดสถานะรวม
    if result['pdf'] == 'Yes' and result['attachments'] == 'Yes':
        result['status'] = 'Complete'
    elif result['pdf'] == 'Yes' and result['attachments'] == 'No':
        result['status'] = 'PDF Only'
    elif result['pdf'] == 'No' and result['attachments'] == 'Yes':
        result['status'] = 'Attachments Only'
    else:
        result['status'] = 'Incomplete'

    # รวม notes
    result['notes'] = '; '.join(result['notes']) if result['notes'] else 'No files'

    return result

def generate_report():
    """
    สแกนโฟลเดอร์ output_ritm และสร้างรายงาน
    """
    print("="*80)
    print("RITM File Completeness Check")
    print("="*80)
    print(f"Output directory: {OUTPUT_DIR.resolve()}")
    print(f"Log file: {DOWNLOADED_LOG.resolve()}")
    print(f"Report file: {REPORT_FILE.resolve()}")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)
    print()

    # Load downloaded RITMs
    downloaded = load_downloaded()

    if not downloaded:
        print("[ERROR] No downloaded RITMs found in log file.")
        print(f"Log file: {DOWNLOADED_LOG}")
        return

    print(f"Found {len(downloaded)} RITM(s) in log file")
    print()

    if not OUTPUT_DIR.exists():
        print(f"[ERROR] Output directory not found: {OUTPUT_DIR}")
        return

    # ตรวจสอบแต่ละ RITM
    print("Checking files...")
    print("-" * 80)

    results = []
    for ritm_number in sorted(downloaded):
        result = check_ritm_folder(ritm_number)
        results.append(result)

        # แสดงสถานะ
        status_icons = {
            'Complete': '✓',
            'PDF Only': '!',
            'Attachments Only': '!',
            'Incomplete': '✗',
            'Folder Missing': '✗'
        }
        icon = status_icons.get(result['status'], '?')
        
        print(f"[{icon}] {result['ritm_number']:15s} | "
              f"PDF: {result['pdf']:3s} | "
              f"Att: {result['attachments']:3s} ({result['attachment_count']:2d} files) | "
              f"Status: {result['status']}")

    # สร้าง CSV report
    print()
    print(f"Generating CSV report: {REPORT_FILE}")

    with open(REPORT_FILE, 'w', newline='', encoding='utf-8-sig') as csvfile:
        fieldnames = [
            'RITM Number',
            'Status',
            'Folder Exists',
            'PDF',
            'PDF Size (KB)',
            'Attachments',
            'Attachment Count',
            'Attachment Files',
            'Notes'
        ]

        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for result in results:
            writer.writerow({
                'RITM Number': result['ritm_number'],
                'Status': result['status'],
                'Folder Exists': result['folder_exists'],
                'PDF': result['pdf'],
                'PDF Size (KB)': f"{result['pdf_size_kb']:.1f}" if result['pdf_size_kb'] > 0 else '0',
                'Attachments': result['attachments'],
                'Attachment Count': result['attachment_count'],
                'Attachment Files': ', '.join(result['attachment_files']) if result['attachment_files'] else '',
                'Notes': result['notes']
            })

    # สรุปผลรวม
    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    
    total = len(results)
    complete = sum(1 for r in results if r['status'] == 'Complete')
    pdf_only = sum(1 for r in results if r['status'] == 'PDF Only')
    att_only = sum(1 for r in results if r['status'] == 'Attachments Only')
    incomplete = sum(1 for r in results if r['status'] == 'Incomplete')
    folder_missing = sum(1 for r in results if r['status'] == 'Folder Missing')
    
    has_pdf = sum(1 for r in results if r['pdf'] == 'Yes')
    has_att = sum(1 for r in results if r['attachments'] == 'Yes')

    print(f"Total RITMs:                     {total}")
    print(f"Complete (PDF + Attachments):    {complete:4d} ({complete/total*100:5.1f}%)")
    print(f"PDF Only (no Attachments):       {pdf_only:4d} ({pdf_only/total*100:5.1f}%)")
    print(f"Attachments Only (no PDF):       {att_only:4d} ({att_only/total*100:5.1f}%)")
    print(f"Incomplete (no files):           {incomplete:4d} ({incomplete/total*100:5.1f}%)")
    print(f"Folder Missing:                  {folder_missing:4d} ({folder_missing/total*100:5.1f}%)")
    print()
    print(f"RITMs with PDF:                  {has_pdf:4d} ({has_pdf/total*100:5.1f}%)")
    print(f"RITMs with Attachments:          {has_att:4d} ({has_att/total*100:5.1f}%)")
    print()
    print(f"✓ Report saved to: {REPORT_FILE.resolve()}")

    # คำแนะนำ
    total_incomplete = pdf_only + att_only + incomplete + folder_missing
    if total_incomplete > 0:
        print()
        print("=" * 80)
        print("RECOMMENDATION")
        print("=" * 80)
        print()
        print(f"Found {total_incomplete} RITM(s) with incomplete files.")
        print()
        print("To re-download incomplete RITMs:")
        print("1. Remove the RITM numbers from downloaded_ritm.log")
        print("2. Run: python 04_export_service_request.py")
        print()
        print("List of incomplete RITMs:")
        for result in results:
            if result['status'] != 'Complete':
                print(f"  - {result['ritm_number']} ({result['status']})")

def main():
    generate_report()

if __name__ == "__main__":
    main()
