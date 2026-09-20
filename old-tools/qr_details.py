#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qr_details.py
=============
Companion to balady_certs.py.

Every Balady certificate PDF carries a small QR code (bottom-left). It points at
a Balady page that publishes the establishment's contact details. This script:

  1. pulls the QR image straight out of each PDF,
  2. decodes it to a URL,
  3. fetches that URL,
  4. extracts name / owner / phone / email / city / activity,
  5. writes one CSV row per certificate.

No browser needed — the target page embeds its data as JSON, so a plain HTTP
request is enough. That makes this far lighter on the portal than the
certificate downloader.

Usage
-----
    python qr_details.py                     # process ./pdf_files, write qr_details.csv
    python qr_details.py --limit 5           # just the first 5 (good for a trial)
    python qr_details.py --pdf-dir some/dir --out other.csv
    python qr_details.py --show              # also print each record as it goes

Re-running skips PDFs already present in the CSV, so it is safe to interrupt.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

try:
    import cv2
    # These QR codes declare an ECI block that OpenCV does not implement. It
    # decodes them correctly anyway, but logs a scary warning per image — mute it.
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)
except ImportError:
    sys.exit("opencv is missing.  Install it with:\n"
             "    .venv/bin/pip install opencv-python-headless")
except AttributeError:
    pass

DEFAULT_PDF_DIR = Path(__file__).resolve().parent / "pdf_files"
DEFAULT_OUT = DEFAULT_PDF_DIR / "qr_details.csv"

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/149.0 Safari/537.36")

# Value fields on the target page are rendered as "$Name$pyCaption":"value".
# The same map also holds *labels* as "Name$pyCaption":"اسم المنشأة" — the
# leading $ is the only thing distinguishing a value from its label, so the
# regex below requires it.
VALUE_RE = re.compile(r'"\$([A-Za-z][A-Za-z0-9 _]*)\$pyCaption":"([^"]*)"')
AJAXCT_RE = re.compile(r"<div id='AJAXCT' data-json='(.*?)'></div>", re.S)

# csv column -> key in the page's caption map
FIELDS = [
    ("facility_name", "FacilityName"),
    ("owner_name",    "ownerName"),
    ("phone",         "CCPhoneNumber"),
    ("email",         "EmailAddress"),
    ("city",          "CCCity"),
    ("region",        "Region"),
    ("activity",      "ISICName"),
    ("fax",           "CCFaxNumber"),
]

COLUMNS = (["pdf_file", "cert_no", "uid"]
           + [c for c, _ in FIELDS]
           + ["case_id", "classification_type", "qr_url"])


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# --------------------------------------------------------------------------
# QR extraction
# --------------------------------------------------------------------------

def qr_url_from_pdf(pdf: Path) -> str | None:
    """Pull the QR out of a PDF and decode it to a URL.

    The QR is a genuine embedded image object (typically 120x120 RGB, <1 KB),
    so `pdfimages` recovers it losslessly. That is much more reliable than
    rendering the page and hunting for it — at page resolution the code is too
    small for the detector to lock onto.
    """
    tmp = Path(tempfile.mkdtemp(prefix="qr_"))
    try:
        subprocess.run(["pdfimages", "-png", str(pdf), str(tmp / "img")],
                       check=True, capture_output=True)
        detector = cv2.QRCodeDetector()
        # smallest first: the QR is tiny next to the header artwork
        for img_path in sorted(tmp.glob("*.png"), key=lambda p: p.stat().st_size):
            img = cv2.imread(str(img_path))
            if img is None:
                continue
            h, w = img.shape[:2]
            if not (40 <= w <= 800 and 0.8 <= w / h <= 1.25):
                continue                      # QR codes are small and square
            for scale in (1, 3, 6):
                im = img if scale == 1 else cv2.resize(
                    img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
                try:
                    text, _, _ = detector.detectAndDecode(im)
                except cv2.error:
                    continue
                if text and "balady" in text.lower():
                    return text
        return None
    except subprocess.CalledProcessError as exc:
        log(f"    pdfimages failed: {exc.stderr.decode()[:120]}")
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------
# Fetch + parse
# --------------------------------------------------------------------------

def fetch(url: str, timeout: int = 60) -> str:
    """GET the QR target, following the 307 and carrying cookies.

    Pega issues a redirect that establishes a session, so the cookie jar
    matters — without it the second hop comes back empty.
    """
    jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [("User-Agent", UA), ("Accept-Language", "ar,en;q=0.8")]
    with opener.open(url, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse(page: str) -> dict:
    """Pull the record out of the page's embedded JSON/caption data."""
    out: dict[str, str] = {}

    caps = {k: html.unescape(v) for k, v in VALUE_RE.findall(page)}
    for col, key in FIELDS:
        out[col] = caps.get(key, "")

    m = AJAXCT_RE.search(page)
    if m:
        try:
            data = json.loads(html.unescape(m.group(1)))
            cd = data.get("Initial", {}).get("CertificateDetails", {})
            out["uid"] = cd.get("CRorLICNumber", "")
            out["case_id"] = cd.get("CaseID", "")
            out["classification_type"] = cd.get("ClassificationType", "")
        except (json.JSONDecodeError, AttributeError):
            pass
    out.setdefault("uid", "")
    out.setdefault("case_id", "")
    out.setdefault("classification_type", "")
    return out


# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pdf-dir", default=str(DEFAULT_PDF_DIR),
                    help="folder of certificate PDFs (default: ./pdf_files)")
    ap.add_argument("--out", default=None,
                    help="CSV to write (default: <pdf-dir>/qr_details.csv)")
    ap.add_argument("--limit", type=int, default=0, help="stop after N PDFs (0 = all)")
    ap.add_argument("--delay", type=float, default=1.5,
                    help="seconds between requests (default 1.5)")
    ap.add_argument("--show", action="store_true", help="print each record")
    ap.add_argument("--retry-failed", action="store_true",
                    help="also retry rows previously recorded as errors")
    args = ap.parse_args()

    pdf_dir = Path(args.pdf_dir).expanduser().resolve()
    out_csv = Path(args.out).expanduser().resolve() if args.out else pdf_dir / "qr_details.csv"
    if not pdf_dir.is_dir():
        sys.exit(f"No such folder: {pdf_dir}")

    pdfs = sorted(pdf_dir.glob("*.pdf"))
    if not pdfs:
        sys.exit(f"No PDFs in {pdf_dir}")

    # resume: skip anything already recorded
    done: set[str] = set()
    if out_csv.exists():
        with out_csv.open(encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                if args.retry_failed and (row.get("qr_url") or "").startswith("ERROR"):
                    continue
                done.add(row.get("pdf_file", ""))

    todo = [p for p in pdfs if p.name not in done]
    if args.limit:
        todo = todo[:args.limit]

    log(f"{len(pdfs)} PDFs in {pdf_dir}")
    log(f"{len(done)} already done, {len(todo)} to process")
    if not todo:
        log("Nothing to do.")
        return 0

    new_file = not out_csv.exists()
    fh = out_csv.open("a", newline="", encoding="utf-8-sig")
    writer = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
    if new_file:
        writer.writeheader()

    ok = noqr = failed = 0
    started = time.time()
    try:
        for i, pdf in enumerate(todo, 1):
            # the downloader names files "<certNo>_<uid>_شهادة التصنيف.pdf"
            parts = pdf.name.split("_")
            cert_no = parts[0] if parts else ""
            uid_from_name = parts[1] if len(parts) > 1 else ""

            url = qr_url_from_pdf(pdf)
            if not url:
                noqr += 1
                log(f"  [{i}/{len(todo)}] {pdf.name[:46]} — no QR found")
                writer.writerow({"pdf_file": pdf.name, "cert_no": cert_no,
                                 "uid": uid_from_name, "qr_url": "ERROR: no QR"})
                fh.flush()
                continue

            try:
                rec = parse(fetch(url))
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                failed += 1
                log(f"  [{i}/{len(todo)}] {pdf.name[:46]} — fetch failed: {type(exc).__name__}")
                writer.writerow({"pdf_file": pdf.name, "cert_no": cert_no,
                                 "uid": uid_from_name, "qr_url": f"ERROR: {type(exc).__name__}"})
                fh.flush()
                time.sleep(args.delay)
                continue

            rec["pdf_file"] = pdf.name
            rec["cert_no"] = cert_no
            rec["qr_url"] = url
            if not rec.get("uid"):
                rec["uid"] = uid_from_name
            elif uid_from_name and rec["uid"] != uid_from_name:
                # the page should describe the same establishment as the file
                log(f"      WARNING: filename uid {uid_from_name} != page uid {rec['uid']}")

            writer.writerow(rec)
            fh.flush()
            ok += 1

            if args.show:
                log(f"  [{i}/{len(todo)}] {rec['uid']}  {rec['facility_name']}")
                log(f"      owner: {rec['owner_name']}   phone: {rec['phone']}   {rec['email']}")
            else:
                log(f"  [{i}/{len(todo)}] {rec['uid']}  {rec['facility_name'][:38]}  {rec['phone']}")

            time.sleep(args.delay)
    except KeyboardInterrupt:
        log("Interrupted — progress saved, rerun to resume.")
    finally:
        fh.close()

    mins = (time.time() - started) / 60
    print()
    log(f"Done in {mins:.1f} min — {ok} records, {noqr} without a QR, {failed} fetch failures")
    log(f"CSV: {out_csv}")
    return 0 if not (noqr or failed) else 1


if __name__ == "__main__":
    sys.exit(main())
