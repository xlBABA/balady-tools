#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run.py — one command, whole pipeline.

    1. ask which city you want (or take --city)
    2. make a folder named after today's date
    3. download the certificate PDFs into it
    4. read every PDF's QR code and pull the contact details
    5. write a clean Excel file with just: company, phone, company no., owner, email

Usage
-----
    python run.py                     # asks for the city, then does everything
    python run.py --city الرياض        # skip the question
    python run.py --limit 5           # small trial run
    python run.py --mobiles-only      # drop rows whose phone is not 05x

Safe to interrupt: every stage resumes, so re-running the same command
continues where it stopped instead of starting over.
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = str(HERE / ".venv" / "bin" / "python")
if not Path(PY).exists():                 # fall back to whatever runs this file
    PY = sys.executable

# A menu of the larger cities. You are NOT limited to these — type any city
# name at the prompt and the downloader validates it against the live list
# (and prints the real options if it does not match).
COMMON_CITIES = [
    "الرياض", "جدة", "مكة المكرمة", "المدينة المنورة", "الدمام", "الخبر",
    "الظهران", "الطائف", "تبوك", "بريدة", "عنيزة", "حائل", "أبها",
    "خميس مشيط", "نجران", "جازان", "الباحة", "سكاكا", "عرعر", "القطيف",
    "الجبيل", "ينبع", "الأحساء", "الهفوف", "حفر الباطن", "الخرج",
    "المجمعة", "الزلفي", "الدوادمي", "شقراء", "بيشة", "القنفذة",
    "رابغ", "الليث", "صبياء", "صامطه", "أبي عريش", "محائل عسير",
    "بلجرشي", "النماص", "رفحاء", "طريف", "القريات", "دومة الجندل",
    "العلا", "ضباء", "الوجه", "أملج", "الرس", "المذنب",
]

# Final spreadsheet: exactly these columns, in this order.
EXCEL_COLUMNS = [
    ("facility_name", "اسم المنشأة / Company"),
    ("phone",         "رقم الهاتف / Phone"),
    ("uid",           "الرقم الوطني / Company no."),
    ("expiry",        "تاريخ الانتهاء / Expiry"),
    ("owner_name",    "اسم المالك / Owner"),
    ("email",         "البريد الإلكتروني / Email"),
]
TEXT_COLUMNS = {"phone", "uid", "expiry"}   # keep leading zeros, keep dd/mm/yyyy intact


def log(msg: str = "") -> None:
    print(msg, flush=True)


def banner(step: str, title: str) -> None:
    log()
    log("=" * 64)
    log(f"  {step}  {title}")
    log("=" * 64)


# --------------------------------------------------------------------------
# 1. pick a city
# --------------------------------------------------------------------------

def choose_city() -> str:
    log()
    log("Which city?  (المدينة)")
    log()
    for i, name in enumerate(COMMON_CITIES, 1):
        end = "\n" if i % 4 == 0 else ""
        print(f"  {i:>2}) {name:<18}", end=end, flush=True)
    if len(COMMON_CITIES) % 4:
        print()
    log()
    log("  Enter a number, or type any city name (Arabic).")

    while True:
        try:
            raw = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            log("\nCancelled.")
            sys.exit(1)
        if not raw:
            continue
        if raw.isdigit():
            n = int(raw)
            if 1 <= n <= len(COMMON_CITIES):
                return COMMON_CITIES[n - 1]
            log(f"  Pick 1-{len(COMMON_CITIES)}, or type a name.")
            continue
        # typed a name: offer near matches from the menu, but allow anything
        hits = [c for c in COMMON_CITIES if raw in c]
        if len(hits) == 1 and hits[0] != raw:
            log(f"  Using: {hits[0]}")
            return hits[0]
        if len(hits) > 1:
            log("  Matches: " + " · ".join(hits))
            log("  Be more specific, or type the full name exactly.")
            continue
        return raw          # not in the menu — the downloader will validate it


# --------------------------------------------------------------------------
# 2-4. run the stages
# --------------------------------------------------------------------------

def run_stage(name: str, cmd: list[str]) -> int:
    log(f"$ {' '.join(cmd[1:])}")
    log()
    started = time.time()
    rc = subprocess.run(cmd).returncode
    mins = (time.time() - started) / 60
    log()
    log(f"  [{name}] finished in {mins:.1f} min (exit {rc})")
    return rc


# --------------------------------------------------------------------------
# 5. the spreadsheet
# --------------------------------------------------------------------------

def build_excel(csv_path: Path, xlsx_path: Path, mobiles_only: bool) -> tuple[int, int]:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    with csv_path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))

    # The certificate expiry date is not on the QR page — it comes from the
    # results grid, which the downloader already recorded in manifest.csv.
    # Join the two on the company number (uid) rather than re-fetching anything.
    expiry_by_uid: dict[str, str] = {}
    manifest = csv_path.parent / "manifest.csv"
    if manifest.exists():
        with manifest.open(encoding="utf-8-sig", newline="") as fh:
            for m in csv.DictReader(fh):
                uid = (m.get("uid") or "").strip()
                exp = (m.get("expiry") or "").strip()
                if uid and exp:
                    expiry_by_uid[uid] = exp
    for r in rows:
        r["expiry"] = expiry_by_uid.get((r.get("uid") or "").strip(), "")

    clean, dropped = [], 0
    for r in rows:
        if (r.get("qr_url") or "").startswith("ERROR"):
            dropped += 1
            continue
        phone = (r.get("phone") or "").strip()
        if mobiles_only and not phone.startswith("05"):
            dropped += 1
            continue
        clean.append(r)

    wb = Workbook()
    ws = wb.active
    ws.title = "جهات الاتصال"
    ws.sheet_view.rightToLeft = True

    head_fill = PatternFill("solid", fgColor="1F6F5C")
    head_font = Font(bold=True, color="FFFFFF", size=11)
    for c, (_, title) in enumerate(EXCEL_COLUMNS, 1):
        cell = ws.cell(row=1, column=c, value=title)
        cell.fill, cell.font = head_fill, head_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 30

    for i, r in enumerate(clean, 2):
        for c, (key, _) in enumerate(EXCEL_COLUMNS, 1):
            cell = ws.cell(row=i, column=c, value=(r.get(key) or "").strip())
            if key in TEXT_COLUMNS:
                # Excel would otherwise eat the leading 0 of 05xxxxxxxx and
                # render the 10-digit company number as 7.04201E+09
                cell.number_format = "@"
                cell.alignment = Alignment(horizontal="left")

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(EXCEL_COLUMNS))}{len(clean) + 1}"
    for c, (key, title) in enumerate(EXCEL_COLUMNS, 1):
        longest = max([len(title)] + [len((r.get(key) or "")) for r in clean] or [12])
        ws.column_dimensions[get_column_letter(c)].width = min(max(longest + 2, 14), 48)

    wb.save(xlsx_path)
    return len(clean), dropped


# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--city", help="skip the prompt and use this city")
    ap.add_argument("--limit", type=int, default=0,
                    help="how many certificates (0 = as many as reachable, ~100)")
    ap.add_argument("--folder", help="output folder name (default: today's date)")
    ap.add_argument("--mobiles-only", action="store_true",
                    help="keep only rows whose phone starts with 05")
    ap.add_argument("--delay", type=float, default=2.0, help="seconds between downloads")
    ap.add_argument("--skip-download", action="store_true",
                    help="reuse PDFs already in the folder; start at the QR step")
    args = ap.parse_args()

    city = args.city or choose_city()
    folder = HERE / (args.folder or date.today().isoformat())
    folder.mkdir(parents=True, exist_ok=True)

    log()
    log(f"  City   : {city}")
    log(f"  Folder : {folder}")
    log(f"  Limit  : {'all reachable (~100)' if args.limit == 0 else args.limit}")

    overall = time.time()

    # ---- stage 1: download -------------------------------------------------
    if not args.skip_download:
        banner("STEP 1/3", "Downloading certificate PDFs")
        cmd = [PY, str(HERE / "balady_certs.py"), "--city", city,
               "--outdir", str(folder), "--delay", str(args.delay),
               "--limit", str(args.limit)]
        rc = run_stage("download", cmd)
        # exit 1 just means "some rows failed" — the rest are still usable,
        # so we carry on rather than abandoning the whole pipeline
        if rc not in (0, 1):
            log("  Download stage failed outright — stopping.")
            return rc
    else:
        banner("STEP 1/3", "Skipped (--skip-download)")

    pdfs = sorted(folder.glob("*.pdf"))
    log(f"  PDFs in folder: {len(pdfs)}")
    if not pdfs:
        log("  No PDFs were downloaded, so there is nothing to read. Stopping.")
        log("  Tip: check the city name, or widen the date range.")
        return 1

    # ---- stage 2: QR -------------------------------------------------------
    banner("STEP 2/3", "Reading QR codes and fetching contact details")
    rc = run_stage("qr", [PY, str(HERE / "qr_details.py"), "--pdf-dir", str(folder)])
    if rc not in (0, 1):
        log("  QR stage failed outright — stopping.")
        return rc

    csv_path = folder / "qr_details.csv"
    if not csv_path.exists():
        log("  No qr_details.csv was produced — stopping.")
        return 1

    # ---- stage 3: Excel ----------------------------------------------------
    banner("STEP 3/3", "Building the Excel file")
    xlsx = folder / f"contacts_{date.today().isoformat()}.xlsx"
    kept, dropped = build_excel(csv_path, xlsx, args.mobiles_only)
    log(f"  Wrote {xlsx.name}")
    log(f"  {kept} rows kept" + (f", {dropped} skipped" if dropped else ""))

    # ---- summary -----------------------------------------------------------
    mins = (time.time() - overall) / 60
    log()
    log("=" * 64)
    log(f"  DONE in {mins:.1f} min")
    log("=" * 64)
    log(f"  City        : {city}")
    log(f"  Folder      : {folder}")
    log(f"  PDFs        : {len(pdfs)}")
    log(f"  Contacts    : {kept}")
    log(f"  Excel       : {xlsx}")
    log()
    log(f"  Open it:  xdg-open '{xlsx}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
