# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Python-based ServiceNow automation project using Playwright for browser automation. The project automates:
1. SSO/MFA authentication with ServiceNow instances
2. Exporting change requests and their attachments from ServiceNow

## Environment Setup

**Python Version**: 3.11.3

### Initial Setup
```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On macOS/Linux
# .venv\Scripts\activate   # On Windows

# Install dependencies
pip install playwright
playwright install chromium
```

### Running Scripts

**Step 1: Login and Save Session**
```bash
python 01_login_save_state.py
```
- Opens browser in non-headless mode (you must see the window)
- Navigate through SSO/MFA manually in the browser
- Waits up to 10 minutes for authentication
- Saves session state to `state.json`

**Step 2: Export Change Requests**
```bash
python 02_export_changes.py
```
- Uses saved session from `state.json`
- Exports change requests to `output/` directory
- Creates folders per change request with PDFs and attachments

## Architecture

### Authentication Flow (01_login_save_state.py)

**Key Components**:
- `BASE`: ServiceNow instance URL (seicthdev.service-now.com)
- `STATE`: Session storage file (state.json)

**Process**:
1. Launches browser (headless=False for SSO/MFA)
2. Navigates to BASE URL
3. Clicks "Login with SSO" button
4. Waits for user to complete SSO/MFA manually
5. Waits for URL pattern `**/now/**` (max 10 min timeout)
6. Saves browser context/cookies to state.json

### Export Automation (02_export_changes.py)

**Key Components**:
- `CHANGE_LIST_URL`: Pre-configured query URL for change request list
- `OUT`: Output directory for exported files
- `safe_name()`: Sanitizes filenames (removes invalid chars, truncates to 150)

**Process Flow**:
1. Loads saved session from state.json
2. Navigates to change request list URL
3. Works within ServiceNow classic UI iframe (`gsft_main`)
4. Iterates through each row in `table.list_table`
5. For each change request:
   - Clicks change number link
   - Exports PDF via "More options" menu
   - Downloads attachments via paperclip icon
   - Handles Supporting Documents tab (UAT SignOff, App Scan, CR File Attachment)
   - Returns to list via browser back button

**Frame Handling**:
ServiceNow classic UI uses iframes. Most selectors target:
```python
frame = page.frame(name="gsft_main") or page
```

**Download Handling**:
- Uses `accept_downloads=True` context option
- `wait_download()` helper saves downloads to target paths
- Handles both single file and "Download All" (zip) scenarios

### Error Handling Patterns

Both scripts use try-except blocks for optional operations:
- PDF export failures are logged but don't stop execution
- Attachment downloads are attempted but failures are non-fatal
- Supporting Documents processing is best-effort

## Development Notes

### Selectors
ServiceNow UI selectors are instance-specific. When selectors fail:
- Run with `headless=False` to inspect elements
- Check if UI is in classic mode (iframe) vs. modern UI
- Adjust button selectors (e.g., "More options", "Export", "PDF")

### Timeouts
- List table load: 60 seconds
- MFA/SSO wait: 10 minutes (600,000ms)
- Menu interactions: 5 seconds

### Output Structure
```
output/
  CHG0000001/
    CHG0000001.pdf
    attachments_download_all.zip
  CHG0000002/
    ...
```

### Pagination
Current implementation processes only the first page of results. To handle multiple pages:
- Locate next page button/link after processing all rows
- Click and wait for new table load
- Continue iteration

## Configuration Points

- `BASE`: ServiceNow instance URL (01_login_save_state.py:4)
- `CHANGE_LIST_URL`: Query URL with filters (02_export_changes.py:10)
- `OUT`: Output directory path (02_export_changes.py:7)
- `headless=False/True`: Browser visibility (both files)

## Thai Language Comments

The code contains Thai language comments for local developers. Key translations:
- "เห็นหน้าจอ" = "see the screen"
- "รอนานสุด" = "wait maximum"
- "ให้เสร็จ" = "until complete"
