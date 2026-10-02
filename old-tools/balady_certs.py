#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
balady_certs.py
===============
Bulk-download classification certificates (شهادة التصنيف) from the Saudi
Balady portal service "التحقق من شهادة التصنيف - التأهيل".

    https://apps.balady.gov.sa/Eservices/MServices/Home/Anonymous?id=190

The service is a Pega BPM app embedded in an iframe. This script fills the
advanced-search form, submits it, and downloads the first N certificate PDFs
from the results grid, preserving the portal's original filenames.

Usage
-----
    python balady_certs.py                      # use the defaults below
    python balady_certs.py --limit 10           # first 10 rows
    python balady_certs.py --headed             # watch it work
    python balady_certs.py --city جدة --from 01/01/2027
    python balady_certs.py --list-options       # dump every dropdown's options and exit

See README.md in this directory for setup and for why the code does the odd
things it does.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import (
    Error as PWError,
    TimeoutError as PWTimeout,
    sync_playwright,
)

# --------------------------------------------------------------------------
# Defaults — override any of these from the command line
# --------------------------------------------------------------------------

PORTAL_URL = "https://apps.balady.gov.sa/Eservices/MServices/Home/Anonymous?id=190"
IFRAME_SELECTOR = "#PegaGadgetIfr"

DEFAULTS = {
    "city":   "الرياض",                 # المدينة
    "ctype":  "منشآت مصنفة",            # نوع التصنيف / التأهيل
    "field":  "مجال التشييد والبناء",    # المجال
    "grade":  "درجة اعتماد",            # درجة التصنيف / التأهيل
    "date_from": "30/09/2026",          # تاريخ انتهاء الشهادة (من)
    "date_to": None,                    # تاريخ انتهاء الشهادة (إلى) — None = leave empty
    "limit": 5,
    # PDFs go into a pdf_files/ subfolder next to this script, not beside it.
    # Created automatically on first run.
    "outdir": str(Path(__file__).resolve().parent / "pdf_files"),
}

# Each dropdown is identified by the Pega property it writes to, taken from the
# hidden <input class="selectedValueProperty"> inside the widget. These ids are
# stable and language-independent — far safer than matching Arabic label text,
# and immune to the DOM-order problem described in README.md.
PROP_CITY  = "City"                  # المدينة
PROP_TYPE  = "Classification"        # نوع التصنيف / التأهيل
PROP_FIELD = "EstablishmentSector"   # المجال
PROP_GRADE = "ClassificationGrade"   # درجة التصنيف / التأهيل
# (a fifth dropdown, PriceCategory / الخدمة لإظهار السعر, is left untouched)

AR_MONTHS = [
    "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
    "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر",
]

# Pega is slow. These are deliberately generous.
T_LOAD      = 60_000   # iframe / first paint
T_CASCADE   = 30_000   # dropdown repopulate after a dependent change
T_SEARCH    = 180_000  # search round-trip (can fire 500+ requests)
T_DOWNLOAD  = 120_000  # PDF is rendered on demand, ~15s typical


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# --------------------------------------------------------------------------
# JS helpers injected into the Pega frame
# --------------------------------------------------------------------------

# Inventory every .dga-select widget: which Pega property it writes to, its
# human label, its current value and its options.
#
# Why identify by property rather than position: document.querySelectorAll
# ('.dga-select') does NOT return the widgets in the order they appear on
# screen. Indexing positionally silently writes your value into the wrong
# field. The hidden .selectedValueProperty input gives each widget a stable id
# (City, Classification, EstablishmentSector, ClassificationGrade, …).
#
# Note the label has to skip <script>/<style>: Pega renders a large inline
# jQuery init block right next to each field, and naive textContent picks that
# up instead of the caption.
JS_FIELDS = """
() => {
  const labelFor = (w) => {
    let el = w;
    for (let i = 0; i < 6; i++) {
      el = el.parentElement;
      if (!el) break;
      const clone = el.cloneNode(true);
      clone.querySelectorAll('.dga-select, script, style').forEach(x => x.remove());
      const t = (clone.textContent || '').replace(/\\s+/g, ' ').trim();
      if (t) return t;
    }
    return '';
  };
  return Array.from(document.querySelectorAll('.dga-select')).map((w, i) => {
    const hidden = w.querySelector('.selectedValueProperty');
    const name = hidden ? (hidden.name || hidden.id || '') : '';
    const m = name.match(/\\$p([A-Za-z0-9_]+)$/);
    return {
      index: i,
      prop: m ? m[1] : name,
      label: labelFor(w),
      value: (w.querySelector('.dga-select__value') || {}).textContent?.trim() || '',
      options: Array.from(w.querySelectorAll('[role=option]'))
        .filter(o => o.getAttribute('data-value') !== '')
        .map(o => ({ value: o.getAttribute('data-value'), text: o.textContent.trim() })),
    };
  });
}
"""

# Read the visible rows of the results grid: national/licence number, facility
# name, expiry, status. Used for the manifest and to detect when a page-change
# has actually landed.
JS_ROWS = """
() => {
  const out = [];
  document.querySelectorAll('tr').forEach(tr => {
    const td = tr.querySelectorAll('td');
    if (td.length < 6) return;
    const uid = (td[0].textContent || '').trim();
    if (!/^[0-9]{8,12}$/.test(uid)) return;      // data rows start with the UID
    // Grab the row's download button name in the SAME pass as its uid, so the
    // two can never drift apart. Each row has two buttons; the certificate one
    // is CCLCertifDownloadForSearch_*, the other is عرض التفاصيل.
    const btn = tr.querySelector('button[name^="CCLCertifDownloadForSearch"]');
    out.push({
      uid,
      name:   (td[1].textContent || '').trim(),
      expiry: (td[2].textContent || '').trim(),
      status: (td[3].textContent || '').trim(),
      ctype:  (td[4].textContent || '').trim(),
      btn:    btn ? btn.getAttribute('name') : null,
    });
  });
  return out;
}
"""

# Pager state: which page links exist, which is current, how many pages total.
JS_PAGER = """
() => {
  const pages = [];
  let current = null;
  document.querySelectorAll('a[aria-label*="الصفحة"]').forEach(a => {
    const n = parseInt((a.textContent || '').trim(), 10);
    if (!Number.isInteger(n)) return;
    pages.push(n);
    if ((a.getAttribute('aria-label') || '').includes('الحالية')) current = n;
  });
  const m = (document.body.textContent || '').match(/الصفحة\\s+\\d+\\s+من\\s+(\\d+)/);
  return {pages, current, total: m ? parseInt(m[1], 10) : null};
}
"""

JS_HIDDEN_DATES = """
() => {
  const g = n => {
    const el = document.querySelector('input[name="$PpyDisplayHarness$p' + n + '"]');
    return el ? el.value : null;
  };
  return { start: g('StartDate'), end: g('EndDate') };
}
"""


# --------------------------------------------------------------------------
# Small utilities
# --------------------------------------------------------------------------

def js_click(locator) -> None:
    """Click via a synthetic DOM event.

    The Balady page's sticky header sits on top of the iframe and swallows real
    pointer events near the top of the frame (Playwright reports
    '<div class="container top-header"> intercepts pointer events'). A DOM
    .click() bypasses hit-testing entirely and still fires the jQuery handlers
    Pega binds, so it works where a real click cannot.
    """
    locator.evaluate("el => el.click()")


def safe_click(locator, timeout: int = 8_000) -> None:
    """Real click if possible, synthetic click if something is covering it."""
    try:
        locator.click(timeout=timeout)
    except (PWTimeout, PWError):
        js_click(locator)


def dropdown_index(frame, prop: str) -> int:
    """Resolve a dropdown to its DOM index via its Pega property id."""
    entries = frame.locator("body").evaluate(JS_FIELDS)
    for e in entries:
        if e["prop"] == prop:          # exact: 'Classification' must not match 'ClassificationGrade'
            return e["index"]
    have = " | ".join(f'{e["index"]}:{e["prop"]}' for e in entries)
    raise RuntimeError(f"No dropdown with property {prop!r}. Found: {have}")


def select_dropdown(frame, prop: str, option_text: str) -> None:
    """Open the dga-select bound to Pega property `prop` and pick `option_text`."""
    idx = dropdown_index(frame, prop)
    widget = frame.locator(".dga-select").nth(idx)

    safe_click(widget.locator(".dga-select__trigger"))

    option = widget.locator("[role=option]", has_text=re.compile(rf"^\s*{re.escape(option_text)}\s*$"))
    if option.count() == 0:
        available = [a.strip() for a in widget.locator("[role=option]").all_inner_texts() if a.strip()]
        raise RuntimeError(
            f"Option {option_text!r} not found under {prop}.\nAvailable: {available}"
        )
    safe_click(option.first)

    # Confirm it actually took, rather than assuming.
    value_el = frame.locator(".dga-select").nth(idx).locator(".dga-select__value")
    value_el.wait_for(timeout=T_CASCADE)
    got = value_el.inner_text().strip()
    if got != option_text:
        raise RuntimeError(f"Tried to set {prop}={option_text!r} but it reads {got!r}")
    log(f"  ✓ {prop} = {got}")


def set_date(frame, page, which: str, ddmmyyyy: str) -> None:
    """Fill one end of the expiry date range by driving the calendar widget.

    `which` is 'StartDate' (من) or 'EndDate' (إلى).
    `ddmmyyyy` is the portal's own display format, e.g. '30/09/2026'.
    """
    day, month, year = (int(x) for x in ddmmyyyy.split("/"))
    target_label = f"{AR_MONTHS[month - 1]} {year}"

    # The visible control is a <span>, not an <input>; the value lives in a
    # sibling hidden input that Pega posts back.
    field = frame.locator(f'span[data-ctl*="DateRange"][name="$PpyDisplayHarness$p{which}"]')
    safe_click(field)

    # The picker is rendered INSIDE the Pega iframe, not on the parent page.
    picker = frame.locator(".daterangepicker:visible").first
    picker.wait_for(timeout=T_CASCADE)

    # It shows two months side by side. Rather than assume which pane holds what,
    # read every month header and navigate until the target appears in one of them.
    cal_index = -1
    for _ in range(36):  # 3 years of travel is plenty
        labels = [t.strip() for t in picker.locator("th.month").all_inner_texts()]
        if not labels:
            raise RuntimeError("Date picker opened but has no month headers")
        if target_label in labels:
            cal_index = labels.index(target_label)
            break
        shown_month, shown_year = labels[0].rsplit(" ", 1)
        delta = (year - int(shown_year)) * 12 + (month - 1 - AR_MONTHS.index(shown_month))
        arrow = picker.locator("th.next.available" if delta > 0 else "th.prev.available").first
        if arrow.count() == 0:
            raise RuntimeError(f"Cannot navigate calendar from {labels[0]!r} to {target_label!r}")
        safe_click(arrow)
        page.wait_for_timeout(300)
    if cal_index < 0:
        raise RuntimeError(f"Gave up navigating the calendar to {target_label}")

    # Pick the day within that pane. Cells for neighbouring months carry .off —
    # excluding them is what stops '30' matching 30 August instead of 30 September.
    cal = picker.locator("div.drp-calendar, div.calendar").nth(cal_index)
    cell = cal.locator(f"td.available:not(.off):text-is('{day}')").first
    cell.wait_for(timeout=T_CASCADE)
    safe_click(cell)

    # autoApply is false on this control, so the range is not committed until
    # تطبيق is pressed.
    apply_btn = frame.locator(".daterangepicker:visible button:has-text('تطبيق')").first
    if apply_btn.count():
        safe_click(apply_btn)

    page.wait_for_timeout(600)
    vals = frame.locator("body").evaluate(JS_HIDDEN_DATES)
    key = "start" if which == "StartDate" else "end"
    if vals[key] != ddmmyyyy:
        raise RuntimeError(f"Date {which} should be {ddmmyyyy} but reads {vals[key]!r}")
    log(f"  ✓ {which} = {vals[key]}  (other end: {vals['end' if key == 'start' else 'start']!r})")


def dump_options(frame) -> None:
    """Print every dropdown: property id, label, current value, options."""
    print()
    for e in frame.locator("body").evaluate(JS_FIELDS):
        opts = [o["text"] for o in e["options"]]
        label = e["label"][:70] or "(no label found)"
        print(f'[{e["index"]}] {e["prop"]:<22} {label}')
        print(f'     current: {e["value"]!r}   options: {len(opts)}')
        for o in opts[:40]:
            print(f"       - {o}")
        if len(opts) > 40:
            print(f"       … and {len(opts) - 40} more")
        print()


def result_page_count(frame) -> str:
    """Best-effort 'page X of Y' from the pager. Cosmetic only."""
    try:
        txt = frame.locator("a[aria-label*='من']").first.get_attribute("aria-label") or ""
        m = re.search(r"من\s*(\d+)", txt)
        if m:
            return m.group(1)
    except Exception:
        pass
    return "?"


def already_have(outdir: Path, uid: str):
    """Has this record been downloaded before?

    The portal names files '<certNo>_<uid>_شهادة التصنيف.pdf'. We know the uid
    from the grid before downloading, so globbing on it lets the script resume
    without re-fetching anything — which is what makes interrupting a long run
    free rather than wasteful.
    """
    hits = sorted(outdir.glob(f"*_{uid}_*.pdf"))
    return hits[0] if hits else None


def download_row(page, frame, uid: str, outdir: Path, attempts: int = 2):
    """Download the certificate for `uid`. Returns the saved path or None.

    Addressing rows positionally with .nth(i) is WRONG. After a page turn the
    index stops lining up with the visible rows and you silently download
    someone else's certificate — observed in testing, row 7035944193 on page 2
    produced 7041132932's PDF, a page-1 record. No error, just the wrong file.

    Matching the row by its uid text is also wrong: the uid sits three levels
    deep (<td><div><span>7002530819</span></div></td>), so `td:text-is(...)`
    matches nothing at all, and four nested <tr> elements contain the uid text
    anyway.

    What works: Pega gives every download button a unique, stable name
    (CCLCertifDownloadForSearch_..._pxResults(N)_1, numbered globally across
    pages). JS_ROWS reads that name in the same DOM pass as the uid, so the
    pairing cannot drift. We re-read immediately before each click because the
    pagelist key in the name changes when Pega rebuilds the grid.

    The filename is checked afterwards as a second line of defence — the portal
    names every file '<certNo>_<uid>_…', so a mismatch is detectable.
    """
    for attempt in range(1, attempts + 1):
        try:
            rows = frame.locator("body").evaluate(JS_ROWS)
            entry = next((r for r in rows if r["uid"] == uid), None)
            if not entry or not entry.get("btn"):
                log(f"      {uid} is not on the current page — skipping")
                return None
            btn = frame.locator(f'button[name="{entry["btn"]}"]')
            with page.expect_download(timeout=T_DOWNLOAD) as dl_info:
                safe_click(btn)
            download = dl_info.value
            name = download.suggested_filename

            if f"_{uid}_" not in name:
                log(f"      MISMATCH: asked for {uid}, portal returned {name!r}")
                if attempt < attempts:
                    page.wait_for_timeout(4000)
                    continue
                return None

            dest = outdir / name
            download.save_as(dest)
            return dest
        except (PWTimeout, PWError) as exc:
            if attempt < attempts:
                log(f"      {type(exc).__name__} — retry {attempt + 1}/{attempts}")
                page.wait_for_timeout(4000)
            else:
                log(f"      giving up on {uid}: {type(exc).__name__}")
    return None


def goto_next_page(page, frame, current_first_uid: str) -> bool:
    """Click '>' and wait until the grid really changes. False if no next page."""
    nxt = frame.get_by_role("link", name=">", exact=True)
    if nxt.count() == 0:
        return False
    safe_click(nxt.first)
    for _ in range(90):                       # up to 90s for a slow page turn
        page.wait_for_timeout(1000)
        rows = frame.locator("body").evaluate(JS_ROWS)
        if rows and rows[0]["uid"] != current_first_uid:
            return True
    return False


def goto_page(page, frame, n: int, timeout_s: int = 60) -> bool:
    """Jump straight to result page `n`. True if we end up there.

    This is needed on every single download, because the grid snaps back to
    page 1 each time a certificate is fetched (see README §4.12). One click per
    jump — the pager exposes direct links for the pages in its current window.
    """
    info = frame.locator("body").evaluate(JS_PAGER)
    if info["current"] == n:
        return True
    if not info["pages"]:
        # No pagination links in the DOM at all. The portal renders a pager
        # only when the results overflow one page, so a small result set (a
        # city with <= 10 matches) has none — and we are already on the only
        # page there is. Without this, such searches found their rows and then
        # refused to download any of them.
        return n == 1
    if n not in info["pages"]:
        return False

    rows = frame.locator("body").evaluate(JS_ROWS)
    before = rows[0]["uid"] if rows else None
    link = frame.locator(f'a[aria-label="الصفحة {n}"]')   # exact: "الصفحة 1" must not match "الصفحة 10"
    if link.count() == 0:
        return False
    safe_click(link.first)

    for _ in range(timeout_s):
        page.wait_for_timeout(1000)
        rows = frame.locator("body").evaluate(JS_ROWS)
        if rows and rows[0]["uid"] != before:
            return True
        state = frame.locator("body").evaluate(JS_PAGER)
        if state["current"] == n:
            return True
    return False


# --------------------------------------------------------------------------
# Main flow
# --------------------------------------------------------------------------

def run(args) -> int:
    outdir = Path(args.outdir).expanduser().resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            channel="chrome",          # reuse system Chrome, no extra download
            headless=not args.headed,
        )
        context = browser.new_context(
            accept_downloads=True,
            locale="ar-SA",
            viewport={"width": 1400, "height": 1000},
        )
        page = context.new_page()

        try:
            log(f"Opening portal …")
            page.goto(PORTAL_URL, wait_until="domcontentloaded", timeout=T_LOAD)

            # The Pega app is an iframe on this page. It is NOT a redirect, and
            # the iframe's own mashup URL 500s if you load it directly — the
            # pwmChannelID token is bound to this parent page's handshake.
            page.wait_for_selector(IFRAME_SELECTOR, timeout=T_LOAD)
            frame = page.frame_locator(IFRAME_SELECTOR)

            adv = frame.locator('input[type=radio][value="Advanced Search"]')
            adv.wait_for(timeout=T_LOAD)
            log("Pega app loaded. Switching to بحث متقدم …")
            js_click(adv)   # sticky header covers this one — synthetic click required

            # Wait for the advanced form to render.
            frame.locator(".dga-select").first.wait_for(timeout=T_CASCADE)
            page.wait_for_timeout(1500)

            if args.list_options:
                dump_options(frame)
                # المجال and درجة only populate once نوع التصنيف is chosen, so
                # set it and dump again to show the full picture.
                log(f"Selecting نوع التصنيف = {args.ctype} to reveal cascaded options …")
                select_dropdown(frame, PROP_TYPE, args.ctype)
                page.wait_for_timeout(3000)
                dump_options(frame)
                return 0

            log("Filling the form …")
            # Order matters: نوع التصنيف repopulates المجال and درجة التصنيف.
            select_dropdown(frame, PROP_CITY, args.city)
            select_dropdown(frame, PROP_TYPE, args.ctype)
            page.wait_for_timeout(2500)          # let the cascade land
            select_dropdown(frame, PROP_FIELD, args.field)
            select_dropdown(frame, PROP_GRADE, args.grade)

            if args.date_from:
                set_date(frame, page, "StartDate", args.date_from)
            if args.date_to:
                set_date(frame, page, "EndDate", args.date_to)

            log("Submitting search (this is slow — Pega fires hundreds of requests) …")
            safe_click(frame.locator("button:has-text('بحث')").first)

            # Results are ready when the first download button exists.
            dl_buttons = frame.locator("button:has-text('تنزيل')")
            dl_buttons.first.wait_for(timeout=T_SEARCH)
            page.wait_for_timeout(2000)

            per_page = dl_buttons.count()
            pages = result_page_count(frame)
            est = f"~{per_page * int(pages)}" if pages.isdigit() else "?"
            log(f"Results: {per_page} rows/page, {pages} pages, {est} certificates total")

            target = args.limit if args.limit > 0 else 10 ** 9   # 0 / --all == everything
            if args.limit <= 0:
                log("Downloading EVERYTHING. Ctrl-C is safe — rerun to resume where it stopped.")

            saved, skipped, failed = [], [], []
            manifest_path = outdir / "manifest.csv"
            new_manifest = not manifest_path.exists()
            manifest = manifest_path.open("a", newline="", encoding="utf-8-sig")
            writer = csv.writer(manifest)
            if new_manifest:
                writer.writerow(["page", "uid", "name", "expiry", "status", "type", "file"])

            pager = frame.locator("body").evaluate(JS_PAGER)
            reachable = max(pager["pages"]) if pager["pages"] else 1
            total_pages = pager["total"] or reachable
            if args.max_pages:
                reachable = min(reachable, args.max_pages)

            if total_pages > reachable:
                log(f"NOTE: {total_pages} pages exist, but only pages 1-{reachable} are reachable.")
                log( "      The grid snaps back to page 1 after every download and the pager")
                log(f"      only exposes a {reachable}-page window, so one search tops out at")
                log(f"      ~{reachable * per_page} certificates. To get the rest, narrow the")
                log( "      search (e.g. by date range) and run again — see README §4.12.")

            seen = set()
            started = time.time()
            try:
                for target_page in range(1, reachable + 1):
                    if len(saved) + len(skipped) >= target:
                        break
                    log(f"--- page {target_page}/{total_pages} "
                        f"(saved {len(saved)}, skipped {len(skipped)}, failed {len(failed)}) ---")

                    # Each download resets the grid to page 1, so we re-jump to the
                    # page we are working on before every single fetch.
                    while len(saved) + len(skipped) < target:
                        if not goto_page(page, frame, target_page):
                            log(f"  cannot reach page {target_page}; stopping here")
                            break

                        rows = frame.locator("body").evaluate(JS_ROWS)
                        if not rows:
                            break

                        nxt = None
                        for row in rows:
                            have = already_have(outdir, row["uid"])
                            if have:
                                if row["uid"] not in seen:
                                    seen.add(row["uid"])
                                    skipped.append(row["uid"])
                                    log(f"  · {row['uid']} already downloaded ({have.name})")
                                continue
                            nxt = row
                            break

                        if nxt is None:
                            break                       # every row on this page is done

                        dest = download_row(page, frame, nxt["uid"], outdir)
                        seen.add(nxt["uid"])
                        if dest:
                            saved.append(dest)
                            writer.writerow([target_page, nxt["uid"], nxt["name"], nxt["expiry"],
                                             nxt["status"], nxt["ctype"], dest.name])
                            manifest.flush()            # survive a Ctrl-C
                            done = len(saved) + len(skipped)
                            rate = (time.time() - started) / max(len(saved), 1)
                            left = min(target, reachable * per_page) - done
                            eta = f"  eta ~{int(left * rate / 60)}m" if left > 0 else ""
                            log(f"  [{done}] {dest.name}  ({dest.stat().st_size:,} b){eta}")
                        else:
                            failed.append(nxt["uid"])
                            writer.writerow([target_page, nxt["uid"], nxt["name"], nxt["expiry"],
                                             nxt["status"], nxt["ctype"], "FAILED"])
                            manifest.flush()

                        time.sleep(args.delay)
            except KeyboardInterrupt:
                log("Interrupted — progress is saved, rerun to resume.")
            finally:
                manifest.close()

            mins = (time.time() - started) / 60
            print()
            log(f"Done in {mins:.1f} min — {len(saved)} downloaded, "
                f"{len(skipped)} already present, {len(failed)} failed")
            log(f"Output: {outdir}")
            log(f"Manifest: {manifest_path}")
            if failed:
                log(f"Failed UIDs: {', '.join(failed[:20])}"
                    + (" …" if len(failed) > 20 else ""))
                log("Rerun the same command to retry just those.")
            return 0 if not failed else 1

        except Exception as exc:
            log(f"FAILED: {type(exc).__name__}: {exc}")
            shot = outdir / "error.png"
            try:
                page.screenshot(path=str(shot), full_page=True)
                log(f"Screenshot written to {shot}")
            except Exception:
                pass
            return 2
        finally:
            context.close()
            browser.close()


def main() -> int:
    p = argparse.ArgumentParser(
        description="Download classification certificates from the Balady portal.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--city",   default=DEFAULTS["city"],   help="المدينة")
    p.add_argument("--type",   dest="ctype", default=DEFAULTS["ctype"], help="نوع التصنيف / التأهيل")
    p.add_argument("--field",  default=DEFAULTS["field"],  help="المجال")
    p.add_argument("--grade",  default=DEFAULTS["grade"],  help="درجة التصنيف / التأهيل")
    p.add_argument("--from",   dest="date_from", default=DEFAULTS["date_from"],
                   help="expiry from, dd/mm/yyyy (empty string to skip)")
    p.add_argument("--to",     dest="date_to",   default=DEFAULTS["date_to"],
                   help="expiry to, dd/mm/yyyy")
    p.add_argument("--limit",  type=int, default=DEFAULTS["limit"],
                   help="how many certificates; 0 = every result across all pages")
    p.add_argument("--all",    action="store_true", help="shorthand for --limit 0")
    p.add_argument("--max-pages", type=int, default=0, help="stop after N result pages (0 = no cap)")
    p.add_argument("--outdir", default=DEFAULTS["outdir"], help="where to save the PDFs (default: ./pdf_files)")
    p.add_argument("--delay",  type=float, default=2.0, help="seconds between downloads")
    p.add_argument("--headed", action="store_true", help="show the browser window")
    p.add_argument("--list-options", action="store_true",
                   help="print every dropdown's available options, then exit")
    args = p.parse_args()
    if args.all:
        args.limit = 0
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
