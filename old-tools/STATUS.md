# Project status — Balady certificate downloader

**Last worked on:** 20 September 2026
**Location:** `~/Downloads/test3/`
**State:** two working tools — certificate downloader + QR contact extractor.
One known ceiling (~100 certificates per search).

This file is the handover note: what exists, what was proven, what wasn't, and
where to pick up. For *how the portal works* and *how to install*, read
`README.md` — this file does not repeat it.

---

## TL;DR — resume in 30 seconds

```bash
cd ~/Downloads/test3
.venv/bin/python balady_certs.py --all      # ~100 certificates, ~25 min
```

Safe to Ctrl-C. Rerunning skips whatever is already downloaded. Files land in
this folder.

---

## 1. What this is

Automates the Saudi Balady public lookup **التحقق من شهادة التصنيف - التأهيل**
(<https://apps.balady.gov.sa/Eservices/MServices/Home/Anonymous?id=190>):
fills the advanced search form, submits it, and downloads certificate PDFs from
the results grid, keeping the portal's original filenames.

Default search (all overridable by flag):

| Field | Value |
|---|---|
| المدينة | الرياض |
| نوع التصنيف / التأهيل | منشآت مصنفة |
| المجال | مجال التشييد والبناء |
| درجة التصنيف / التأهيل | درجة اعتماد |
| تاريخ الانتهاء من | 30/09/2026 (i.e. still valid on that date) |

That search returns **~500 results across 50 pages**.

---

## 2. Files here

| File | What |
|---|---|
| `balady_certs.py` | downloads certificate PDFs |
| `qr_details.py` | reads each PDF's QR → contact details CSV (README §9) |
| `make_excel.py` | CSV → formatted .xlsx (README §10) |
| `README.md` | install guide + full technical notes on the portal (~22 KB) |
| `STATUS.md` | this file |
| `requirements.txt` | pinned deps — playwright, opencv-python-headless + transitive |
| `.venv/` | ready-to-run environment (153 MB) |
| `pdf_files/` | **all output** — certificates, `manifest.csv`, `qr_details.csv`, `qr_details.xlsx` |

The tool directory itself stays clean: script, docs, venv, and the one output
folder.

Expect more PDFs than manifest rows: the first 5 were downloaded by hand before
the script existed. They are still correctly skipped on rerun, because resume
checks the *filesystem*, not the manifest.

---

## 3. What is proven vs. what is not

**Verified working:**

- Default 5-certificate run, end to end — output byte-identical (MD5) to the
  same files downloaded by hand.
- 6 consecutive downloads on result page 2 using the final code — 0 failures,
  every UID correct.
- Resume: 12 already-present files correctly detected and skipped.
- Direct page jumps confirmed to pages 1, 2, 5 and 10.
- Integrity of everything on disk: 18 files, 18 valid PDFs, 18 unique
  checksums, 18 distinct UIDs, **zero UID/filename mismatches**.

**Not verified:**

- A complete `--all` run (pages 1–10) has **never been executed start to
  finish.** Pages 1–2 were tested with the final code, and page jumps were
  confirmed up to page 10 separately, but downloads on pages 3–10 have not
  actually been exercised. It uses the same two mechanisms, so it should work —
  but treat the first full run as the real test and watch the first page or two.

---

## 4. The hard limit — read before planning anything

**One search yields at most ~100 certificates.** This is the portal's design,
not a choice made here.

Proven by experiment: **every download resets the results grid to page 1** and
rebuilds the whole pagelist. Not a slow repaint — still page 1 at t+30s. So you
can never walk a page: downloading row 2 of page 2 bounces you back before you
can reach row 3.

The script works around this by re-jumping to its target page before *every
single* download. That is affordable only because the pager offers direct page
links — and it exposes **only a 10-page window**:

- Pages 11–50 have no link at all.
- The `...` button is **inert** — the link list is byte-identical after clicking.
- There is **no page-size control** (no `<select>` anywhere in the frame).

Reaching page 50 would need ~40 sequential `>` clicks *per download* — roughly
8,700 clicks, 12+ hours of pure navigation. Deliberately not built.

### Getting more than 100

Don't fight the pager — **narrow the search so the result set fits in 10 pages**,
and run repeatedly. Everything accumulates in the same folder and resume makes
overlap free:

```bash
.venv/bin/python balady_certs.py --all --from 01/10/2026 --to 31/12/2026
.venv/bin/python balady_certs.py --all --from 01/01/2027 --to 31/03/2027
.venv/bin/python balady_certs.py --all --from 01/04/2027 --to 30/06/2027
```

Slice by expiry range, city, or درجة — anything that partitions the set into
chunks under ~100. **If a run reports more than 10 pages, the slice is too
wide.** The script prints a NOTE when it detects pages it cannot reach.

This partitioning strategy is the main unfinished work. Nobody has mapped how
the ~500 results distribute across expiry dates, so the slice boundaries above
are guesses — check the reported page count and adjust.

---

## 5. Commands

```bash
cd ~/Downloads/test3

.venv/bin/python balady_certs.py                  # 5 (default)
.venv/bin/python balady_certs.py --limit 25       # a specific number
.venv/bin/python balady_certs.py --all            # ~100, pages 1-10
.venv/bin/python balady_certs.py --all --max-pages 3   # smaller bite

.venv/bin/python balady_certs.py --list-options   # dump dropdown values
.venv/bin/python balady_certs.py --headed         # watch the browser
.venv/bin/python balady_certs.py --city جدة --grade الأولى
.venv/bin/python balady_certs.py --outdir ~/Downloads/other-folder
```

Long run, detached:

```bash
nohup .venv/bin/python -u balady_certs.py --all > run.log 2>&1 &
tail -f run.log
```

Full flag table is in `README.md` §3.

---

## 6. Where files are saved

Default output is **`pdf_files/` next to the script**
(`Path(__file__).parent / "pdf_files"`), not your current working directory — so
downloads follow the script if you move it. Created automatically on first run.
Override with `--outdir`.

Three things land there: the PDFs (`<certNo>_<uid>_شهادة التصنيف.pdf`, the
portal's own names), `manifest.csv`, and `error.png` if a run crashes.

**Resume is per-folder** — the skip check globs the output directory for
`*_<uid>_*.pdf`. Use a different `--outdir` and it will re-download everything.

---

## 7. Design decisions worth remembering

- **Verify, never assume.** Every dropdown selection and date is read back and
  the script raises if it disagrees. This is what caught the bugs below.
- **Identify by Pega property, not by label or position.** Dropdowns are keyed
  on `City` / `Classification` / `EstablishmentSector` / `ClassificationGrade`
  (from hidden `.selectedValueProperty` inputs), because
  `querySelectorAll('.dga-select')` does *not* return widgets in visual order.
- **Identify rows by their button name, read atomically with the UID.** See
  below.
- **System Chrome, not bundled Chromium** (`channel="chrome"`) — avoids a
  150 MB download.

### Bugs found and fixed (detail in README §4.10 and §4.12)

1. **Silent wrong-file bug.** `.nth(i)` positional indexing downloaded *another
   company's certificate* after a page turn, with no error at all. Caught only
   by comparing the manifest UID against the filename. Root cause turned out to
   be the page-1 reset (§4). Fixed by clicking
   `button[name="...pxResults(N)_1"]`, read in the same DOM pass as the UID.
2. **A fix that made it worse.** Matching rows via
   `tr:has(td:text-is('<uid>'))` matches **zero elements** — the UID sits three
   levels deep inside `<div><span>`. That produced a 40-minute run with 0
   downloads and 37 failures before it was caught and killed.

The lesson recorded for next time: test the *download* path explicitly. That
second failure hid because page 1 was entirely already-downloaded, so every row
was skipped — the resume path was being tested while the download path had never
run once.

---

## 8. venv — do you actually need it?

Asked and answered, recorded here so it isn't re-litigated.

**No, it's not mandatory.** This machine's system Python has **no
`EXTERNALLY-MANAGED` marker**, so pip will not refuse a plain install. This
works:

```bash
pip install --user playwright
cd ~/Downloads/test3
python3 balady_certs.py        # note: python3, not .venv/bin/python
```

Then `rm -rf .venv` reclaims 153 MB. The script needs no changes.

**Why keep the venv:** `--user` packages are shared by every Python project you
own, so a future project needing a different playwright version will silently
downgrade this one. A venv prevents that, and `rm -rf .venv` is a clean
uninstall.

**The thing that actually breaks systems** is `sudo pip install` — it writes
into `/usr/lib/python3.14/`, which `dnf` itself depends on. Never that.

`requirements.txt` is the real insurance: whatever happens to the environment,
it reconstructs the exact working versions.

---

## 8b. Second tool — qr_details.py

Reads the QR code printed on each certificate and turns it into a contact
spreadsheet (`pdf_files/qr_details.csv`): company number (uid), facility name,
owner name, phone, email, city, region, activity.

```bash
.venv/bin/python qr_details.py            # process every PDF in pdf_files/
.venv/bin/python qr_details.py --limit 5  # trial
```

No browser — one plain HTTP request per certificate, ~6 s each, so ~100 takes
about 10 minutes. Resumable the same way as the downloader. Full technical
write-up in README §9.

Verified on 6 certificates: 6/6 decoded, 6/6 page uid matched the filename uid,
0 failures.

---

## 9. Next steps

1. **Run `--all` once, start to finish**, watching the first couple of pages.
   That closes the one verification gap in §3.
2. **Work out the date slicing** to get past ~100 (§4). Run
   `--list-options` and experiment with `--from`/`--to` ranges, checking the
   reported page count stays ≤10.
3. Optional: if lots of failures ever appear in `manifest.csv`, raise
   `T_DOWNLOAD` or `--delay` in `balady_certs.py`.

## 10. Etiquette

Public, anonymous government service — the URL literally says `Anonymous`, no
login involved. But it renders each PDF on demand, so keep `--delay` at 2 s or
higher and don't run parallel copies. Bulk-hammering a ministry service is the
fast route to an IP block.
