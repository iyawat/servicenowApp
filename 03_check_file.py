#!/usr/bin/env python3
"""
03_check_file.py

ตรวจสอบความสมบูรณ์ของไฟล์ที่ดาวน์โหลดจาก ServiceNow
และสร้างรายงาน CSV

การใช้งาน:
    python 03_check_file.py
"""

import csv
from pathlib import Path
from datetime import datetime

# Configuration
OUTPUT_DIR = Path("output")
REPORT_FILE = Path("file_check_report.csv")


def check_change_folder(change_folder: Path) -> dict:
    """
    ตรวจสอบความสมบูรณ์ของไฟล์ในโฟลเดอร์ Change Request

    Returns:
        dict: สถานะของไฟล์แต่ละประเภท
    """
    change_number = change_folder.name

    result = {
        'change_number': change_number,
        'pdf': 'No',
        'attachments': 'No',
        'uat_signoff': 'No',
        'appscan': 'No',
        'crfile': 'No',
        'notes': []
    }

    # ตรวจสอบ PDF
    pdf_files = list(change_folder.glob(f"{change_number}.pdf"))
    if pdf_files:
        result['pdf'] = 'Yes'
        result['notes'].append(f"PDF: {pdf_files[0].name}")

    # ตรวจสอบ Attachments
    attachment_folder = change_folder / "Attachment"
    if attachment_folder.exists():
        attachment_files = list(attachment_folder.glob("*"))
        if attachment_files:
            result['attachments'] = 'Yes'
            result['notes'].append(f"Attachments: {len(attachment_files)} file(s)")

    # ตรวจสอบ UAT Signoff
    uat_folder = change_folder / "UAT Signoff"
    if uat_folder.exists():
        uat_files = list(uat_folder.glob("*"))
        if uat_files:
            result['uat_signoff'] = 'Yes'
            result['notes'].append(f"UAT: {len(uat_files)} file(s)")

    # ตรวจสอบ AppScan
    appscan_folder = change_folder / "AppScan"
    if appscan_folder.exists():
        appscan_files = list(appscan_folder.glob("*"))
        if appscan_files:
            result['appscan'] = 'Yes'
            result['notes'].append(f"AppScan: {len(appscan_files)} file(s)")

    # ตรวจสอบ CRFile
    crfile_folder = change_folder / "CRFile"
    if crfile_folder.exists():
        crfile_files = list(crfile_folder.glob("*"))
        if crfile_files:
            result['crfile'] = 'Yes'
            result['notes'].append(f"CRFile: {len(crfile_files)} file(s)")

    # รวม notes
    result['notes'] = '; '.join(result['notes']) if result['notes'] else '-'

    return result


def generate_report():
    """
    สแกนโฟลเดอร์ output และสร้างรายงาน CSV
    """
    if not OUTPUT_DIR.exists():
        print(f"[ERROR] Output directory not found: {OUTPUT_DIR}")
        return

    # หา CHG folders ทั้งหมด
    change_folders = sorted([
        f for f in OUTPUT_DIR.iterdir()
        if f.is_dir() and f.name.startswith('CHG')
    ])

    if not change_folders:
        print(f"[WARN] No CHG folders found in {OUTPUT_DIR}")
        return

    print(f"Found {len(change_folders)} change request folders")
    print("Checking files...")

    # ตรวจสอบแต่ละ folder
    results = []
    for change_folder in change_folders:
        result = check_change_folder(change_folder)
        results.append(result)

        # แสดงสถานะ
        status_icons = {
            'Yes': '✓',
            'No': '✗'
        }
        print(f"  {result['change_number']}: "
              f"PDF={status_icons[result['pdf']]} "
              f"Att={status_icons[result['attachments']]} "
              f"UAT={status_icons[result['uat_signoff']]} "
              f"App={status_icons[result['appscan']]} "
              f"CR={status_icons[result['crfile']]}")

    # สร้าง CSV report
    print(f"\nGenerating report: {REPORT_FILE}")

    with open(REPORT_FILE, 'w', newline='', encoding='utf-8-sig') as csvfile:
        fieldnames = [
            'Change Number',
            'PDF',
            'Attachments',
            'UAT Signoff',
            'AppScan',
            'CRFile',
            'Notes'
        ]

        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for result in results:
            writer.writerow({
                'Change Number': result['change_number'],
                'PDF': result['pdf'],
                'Attachments': result['attachments'],
                'UAT Signoff': result['uat_signoff'],
                'AppScan': result['appscan'],
                'CRFile': result['crfile'],
                'Notes': result['notes']
            })

    # สรุปผลรวม
    print(f"\n===== Summary =====")
    print(f"Total changes: {len(results)}")
    print(f"PDF: {sum(1 for r in results if r['pdf'] == 'Yes')}/{len(results)}")
    print(f"Attachments: {sum(1 for r in results if r['attachments'] == 'Yes')}/{len(results)}")
    print(f"UAT Signoff: {sum(1 for r in results if r['uat_signoff'] == 'Yes')}/{len(results)}")
    print(f"AppScan: {sum(1 for r in results if r['appscan'] == 'Yes')}/{len(results)}")
    print(f"CRFile: {sum(1 for r in results if r['crfile'] == 'Yes')}/{len(results)}")
    print(f"\n✓ Report saved to: {REPORT_FILE.resolve()}")


def main():
    print("="*60)
    print("ServiceNow File Completeness Check")
    print("="*60)
    print(f"Output directory: {OUTPUT_DIR.resolve()}")
    print(f"Report file: {REPORT_FILE.resolve()}")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    print()

    generate_report()


if __name__ == "__main__":
    main()
