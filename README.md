# Mobimo Deficiencies & Cases Exporter 📑

A Python automation tool to export, format, and merge apartment deficiencies (*Mängel* & *Baumängel*) from the Mobimo tenant portal into a single consolidated PDF report.

---

## 🛠️ Prerequisites

* **Python 3.12+**
* **Google Chrome** installed on your system

---

## 🚀 Getting Started

### 1. Installation
The script is self-bootstrapping. Simply run the script, and it will automatically set up a local virtual environment (`.venv`), upgrade pip, and install Playwright and PyPDF:

#### Option A: Launch a new browser window (Recommended)
```powershell
python export.py
```

#### Option B: Attach to an existing Chrome instance
If you want to use an already opened Chrome session:
1. Close all active Chrome windows.
2. Launch Chrome with debugging enabled:
   ```powershell
   & "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="c:\dev\mobimo-export\chrome_profile"
   ```
3. Open another terminal and run the exporter:
   ```powershell
   python export.py --cdp 9222
   ```

### Compress PDF so it is lightweight and email-friendly
If you want to compress the generated PDF to make it smaller and more suitable for email, you can use the following command:
```powershell
python.exe compress_pdf.py
```