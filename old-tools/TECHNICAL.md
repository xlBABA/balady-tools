# Balady Certificate Downloader — build & install notes

Automates the Saudi Balady portal service **التحقق من شهادة التصنيف - التأهيل**
(verify classification / qualification certificate), fills the advanced search
form, and downloads certificate PDFs from the results grid.

Service URL: <https://apps.balady.gov.sa/Eservices/MServices/Home/Anonymous?id=190>

This file documents what was built, how to install it, and — most importantly —
**why the code is shaped the way it is**. The portal has several traps that are
not obvious from reading the page, and each one is explained below.

Files in this directory:

| File | Purpose |
|---|---|
| `balady_certs.py` | Downloads certificate PDFs |
| `qr_details.py` | Reads the QR in each PDF → contact details CSV (see §9) |
| `make_excel.py` | CSV → formatted `.xlsx` (see §10) |
| `requirements.txt` | Pinned Python dependencies |
| `.venv/` | Virtual environment (already created, ~153 MB) |
| `pdf_files/` | **All output** — PDFs, `manifest.csv`, `qr_details.csv`, `qr_details.xlsx` |

---

## 1. Quick start

Everything is already installed. From this directory:

```bash
.venv/bin/python balady_certs.py
```

That runs the default search (الرياض / منشآت مصنفة / مجال التشييد والبناء /
درجة اعتماد / expiring on or after 30/09/2026) and saves the first 5 PDFs into
`pdf_files/`, which it creates if it does not exist.

A full run takes roughly **90 seconds**: ~20 s to load, ~20 s for the search,
and ~13 s per PDF.

---

## 2. Installing from scratch

If you move this to another machine, or delete `.venv/`, rebuild it like this.

### 2.1 Prerequisites

- **Python 3.9+** — verified working on Python 3.14.5
- **Google Chrome** — the script drives your *system* Chrome rather than
  downloading its own browser

Check both:

```bash
python3 --version
google-chrome --version
```

### 2.2 Create an isolated environment

A virtual environment ("venv") is a private folder of Python packages. It keeps
this project's dependencies from colliding with anything else on your system,
and it means you never need `sudo pip install`.

```bash
cd ~/Downloads/test3
python3 -m venv .venv
```

### 2.3 Install dependencies

```bash
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

This pulls in:

| Package | Why |
|---|---|
| `playwright` | Browser automation library — the thing that drives Chrome |
| `greenlet` | Playwright's sync API is built on it |
| `pyee` | Event emitter Playwright uses internally |
| `typing_extensions` | Type hints backport |
| `opencv-python-headless` | QR decoding for `qr_details.py` (§9) |
| `numpy` | required by OpenCV |
| `openpyxl` | writes the `.xlsx` in `make_excel.py` (§10) |
| `et_xmlfile` | required by openpyxl |

`qr_details.py` also needs **`pdfimages`**, from poppler-utils. It is already
present on this machine; on a fresh Fedora box: `sudo dnf install poppler-utils`.

### 2.4 Browser binary — usually nothing to do

Playwright normally downloads its own Chromium (~150 MB). This script skips
that by passing `channel="chrome"` to `launch()`, which reuses the Chrome
already installed at `/usr/bin/google-chrome`.

If Chrome is **not** installed, either install it, or download Playwright's
bundled Chromium and remove the `channel="chrome"` line from the script:

```bash
.venv/bin/playwright install chromium
```

### 2.5 Verify

```bash
.venv/bin/python balady_certs.py --list-options
```

If this prints the dropdown inventory (220 cities, 3 classification types, etc.)
the install is good.

---

## 3. Running it

```bash
# defaults
.venv/bin/python balady_certs.py

# a specific number
.venv/bin/python balady_certs.py --limit 10

# watch the browser do it, useful for debugging
.venv/bin/python balady_certs.py --headed

# a different search
.venv/bin/python balady_certs.py --city جدة --grade الأولى --from 01/01/2027

# what can I put in each dropdown?
.venv/bin/python balady_certs.py --list-options
```

### Flags

| Flag | Default | Meaning |
|---|---|---|
| `--city` | `الرياض` | المدينة |
| `--type` | `منشآت مصنفة` | نوع التصنيف / التأهيل |
| `--field` | `مجال التشييد والبناء` | المجال |
| `--grade` | `درجة اعتماد` | درجة التصنيف / التأهيل |
| `--from` | `30/09/2026` | expiry date range start (dd/mm/yyyy) |
| `--to` | *(empty)* | expiry date range end |
| `--limit` | `5` | how many PDFs; **`0` = as many as reachable (~100)** |
| `--all` | off | shorthand for `--limit 0` (pages 1-10, ~100 certs) |
| `--max-pages` | `0` | stop after N result pages (0 = no cap) |
| `--outdir` | `./pdf_files` | where to save (created if missing) |
| `--delay` | `2.0` | seconds between downloads |
| `--headed` | off | show the browser window |
| `--list-options` | off | dump dropdown options and exit |

### Downloading everything

```bash
.venv/bin/python balady_certs.py --all
```

This walks pages 1–10 — **about 100 certificates, ~25 minutes**. That is the
per-search ceiling, not a bug: the grid resets to page 1 after every download
and the pager only exposes 10 pages, so pages 11–50 are unreachable. **§4.12
explains why and how to get the rest** (narrow the search and rerun). The script
prints a NOTE when it detects more pages than it can reach.

Read this before starting it:

- **~15 s per certificate.** Each PDF is rendered on demand server-side, plus
  one page-jump per download. No client-side way to speed that up.
- **It is resumable and safe to interrupt.** Ctrl-C at any point. Before each
  download the script checks for an existing `*_<uid>_*.pdf` in the output
  folder and skips it, so rerunning the same command picks up where it left off
  and costs nothing for what you already have.
- **It writes `manifest.csv`** as it goes (appended and flushed after every
  row, so it survives a kill): page, uid, facility name, expiry, status, type,
  filename. Rows that failed are recorded as `FAILED` — rerun to retry just
  those.
- **Don't lower `--delay` or run several copies at once.** This is a public
  ministry service that does real work per request; bulk-hammering it is both
  rude and the fastest way to get your IP throttled or blocked. The 2-second
  default is already brisk for ~100 sequential requests.

To take a smaller bite first:

```bash
.venv/bin/python balady_certs.py --all --max-pages 5     # first 50
```

Run it detached so it survives closing the terminal:

```bash
nohup .venv/bin/python -u balady_certs.py --all > run.log 2>&1 &
tail -f run.log
```

**On the date fields:** the form has a *range* (من / إلى), not one expiry date.
`--from 30/09/2026` with no `--to` means "certificates expiring **on or after**
30/09/2026" — i.e. still valid on that date. Setting both to the same day means
"expiring exactly that day", which usually returns very few rows.

---

## 4. How the portal actually works

This is the part worth reading. Each item below cost real debugging time.

### 4.1 The app is an iframe, not a redirect

The service URL looks like it redirects to `ccs.balady.gov.sa/prweb/...`, but it
does not. The Pega application is embedded in an iframe on the Balady page:

```html
<iframe id="PegaGadgetIfr" src="https://ccs.balady.gov.sa/prweb/PRAuth/CCSearch/!CCFW/$ContratorSearch/?...&pwmChannelID=MASHUP6c9c..."></iframe>
```

**You cannot load that iframe URL directly** — it returns **HTTP 500**. The
`pwmChannelID` token is bound to the parent page's authentication handshake, so
the iframe only works when reached through the Balady page.

In code, everything happens through a frame locator:

```python
frame = page.frame_locator("#PegaGadgetIfr")
```

Anything you search for on `page` instead of `frame` will simply not be found.
That bit me with the date picker, which also renders inside the iframe.

### 4.2 The parent page's sticky header eats clicks

The Balady wrapper has a sticky header that floats above the top of the iframe.
Clicking the "بحث متقدم" radio with a normal click fails:

```
<div class="container top-header"> from <div class="site-header-cont sticky"> subtree intercepts pointer events
```

Playwright refuses the click because something else would receive it. The fix is
a synthetic DOM click, which bypasses hit-testing entirely and still fires the
jQuery handlers Pega binds:

```python
locator.evaluate("el => el.click()")
```

Only elements near the top of the frame are affected; fields lower down click
normally. The script's `safe_click()` tries a real click first and falls back to
the synthetic one, so it works either way.

### 4.3 The dropdowns are custom widgets, not `<select>`

They are Saudi DGA design-system components:

```html
<div class="dga-select">
  <div class="dga-select__trigger" role="combobox"><span class="dga-select__value">إختيار</span></div>
  <ul class="dga-select__menu" role="listbox">
    <li class="dga-select__option" data-value="الرياض">الرياض</li>
    ...
  </ul>
  <input class="selectedValueProperty" name="$PpyDisplayHarness$pCity" type="hidden">
</div>
```

There is **no native `<select>`**, so Playwright's `select_option()` does
nothing. You must click the trigger, then click the `<li>`.

### 4.4 The big trap: DOM order ≠ visual order

`document.querySelectorAll('.dga-select')` does **not** return the widgets in the
order they appear on screen. Selecting "the 4th dropdown" by position will
silently write your value into the wrong field.

The script therefore identifies each dropdown by the Pega property its hidden
input writes to — stable, language-independent ids:

| Property | Field |
|---|---|
| `City` | المدينة |
| `Classification` | نوع التصنيف / التأهيل |
| `EstablishmentSector` | المجال |
| `ClassificationGrade` | درجة التصنيف / التأهيل |
| `PriceCategory` | الخدمة (لإظهار السعر) |

Matching is **exact**, because `Classification` is a prefix of
`ClassificationGrade` — a substring match would pick the wrong one.

A related nuisance: reading the visible label naively also fails, because Pega
renders a multi-kilobyte inline `<script>` next to each field. The script strips
`<script>` and `<style>` before reading label text.

### 4.5 Two dropdowns are cascading

`المجال` and `درجة التصنيف` are **empty (0 options)** until `نوع التصنيف` is
chosen. Picking `منشآت مصنفة` triggers a server round-trip that repopulates them
(0 → 8 and 0 → 7 options). So the fill order matters:

```
City → Classification → (wait) → EstablishmentSector → ClassificationGrade
```

### 4.6 Two options look almost identical

Under `نوع التصنيف`:

- `منشأت مؤهلة` → `EstablishmentQualification` (qualified establishments)
- `منشآت مصنفة` → `ContractorClassification` (classified establishments) ← the usual one

They differ by two letters and sit next to each other. Easy to pick wrong.

### 4.7 The date field is a range picker with a delayed commit

The visible control is a `<span>`, not an input. The real value lives in a
sibling hidden input (`$PpyDisplayHarness$pStartDate` / `pEndDate`), and the
widget is configured `autoApply: false` — nothing is committed until **تطبيق**
(apply) is pressed.

The calendar shows two months side by side, and the grid includes greyed-out
days from neighbouring months carrying the class `.off`. Because of that, a
September grid contains **two cells reading "30"** — 30 August and 30 September.
Selecting the wrong one silently gives you the wrong date. Hence:

```python
cell = cal.locator(f"td.available:not(.off):text-is('{day}')").first
```

The script navigates months by reading the `th.month` headers and clicking
`th.prev.available` / `th.next.available`, then verifies the hidden input holds
the exact string it intended before continuing.

### 4.8 Results: ~500 rows, 10 per page

A search on the defaults returns about **500 results across 50 pages**. The
portal shows an advisory:

> يرجى تحديد خيارات البحث بشكل أدق لمساعدتك في الحصول على النتائج المطلوبة.
> *("Please narrow your search options…")*

This is **not an error** — results render underneath it. A field also appears
after searching that is not in the initial form: `الخدمة (لإظهار السعر)`.

### 4.9 Downloads are generated on demand and are slow

Clicking **تنزيل** does not return a file immediately. Pega renders the PDF
server-side with PD4ML; it typically arrives **10–15 seconds later**. Polling the
filesystem too early looks like a failure when it is just slow.

Playwright handles this properly:

```python
with page.expect_download(timeout=120_000) as dl_info:
    safe_click(btn)
download = dl_info.value
download.save_as(outdir / download.suggested_filename)
```

`suggested_filename` is the portal's own name, e.g.
`2024014686_7002530819_شهادة التصنيف.pdf` — certificate number, unified national
number, and the Arabic phrase, underscore-separated.

> Note: the Playwright **MCP server** (the browser tooling inside Claude Code)
> sanitises download names, turning `_` and spaces into `-`. The Python API does
> not, so this script keeps the original names with no renaming step.

### 4.10 Never address result rows by position

This caused a **silent wrong-file bug** — the most dangerous thing in this
document, because nothing errored.

The obvious way to download row N is `frame.locator("button:has-text('تنزيل')").nth(N)`.
It works on page 1 and then quietly returns the wrong company's certificate
once you paginate. Caught only by cross-checking the manifest against filenames:

```
row uid  = 7035944193   (شركة الخطوط الفضية للمشاريع)
file uid = 7041132932   ← a page-1 record
```

Two approaches that **do not** work, both tried:

1. `.nth(i)` — breaks as above (the underlying cause is §4.12).
2. `tr:has(td:text-is('<uid>'))` — matches **zero elements**, ever. The uid is
   nested three levels down, so `:text-is()` binds to the innermost `<span>`,
   never the `<td>`:
   ```html
   <td class="dataValueRead gridCell"><div class="oflowDivM"><span>7002530819</span></div></td>
   ```
   Four nested `<tr>` elements also contain each uid, so row-matching is
   ambiguous regardless.

**What works:** Pega gives every button a unique, stable `name`, and the row
index in it is **global across pages** (page 1 = 1–10, page 2 = 11–20, …):

```
CCLCertifDownloadForSearch_D_GetContractClassificationListBySearch_<key>pz.pxResults(12)_1   ← تنزيل
CCContractorSearch_D_GetContractClassificationListBySearch_<key>pz.pxResults(12)_473          ← عرض التفاصيل
```

Each row has *two* buttons, which is why 20 exist but only 10 read تنزيل.
`JS_ROWS` reads the uid **and** its button name in the same DOM pass, so the
pairing cannot drift, and the script clicks `button[name="<exact name>"]`. The
`<key>` changes whenever Pega rebuilds the grid, so the read must happen
immediately before the click.

Second line of defence: the portal names every file `<certNo>_<uid>_…`, so the
script asserts `_<uid>_` appears in the returned filename and retries if not.

**General lesson:** bind each action to a stable identifier read atomically with
the data it belongs to, never to an index — and verify the result when it is
cheap to do so. This bug produced no error at all.

### 4.12 Every download resets the grid to page 1 — this caps a run at ~100

The single most important constraint here, and the real cause of §4.10.

Fetching a certificate makes Pega rebuild the whole result list: the pagelist
key in every button name changes, and the grid **snaps back to page 1**. It is
not a slow repaint — measured still on page 1 at t+30s:

```
page 2 settled   first=7002421613  btn=…pxResults(11)_1
download row 3   → 2024014378_7029695116_…pdf  (correct)
t+0s …  t+30s    first=7002530819  btn=…pxResults(1)_1   ← back to page 1
```

So you can never simply walk a page: downloading row 2 of page 2 throws you back
to page 1 before you can reach row 3. The script therefore **re-jumps to the
page it is working on before every single download**, which costs one click.

That is affordable only because the pager offers direct page links. And it has a
hard ceiling:

- The pager exposes a **10-page window** (`الصفحة 1` … `الصفحة 10`).
- **The `...` button does nothing** — the link list is byte-identical after
  clicking it. Pages 11+ have no link.
- There is **no page-size control** — no `<select>` exists anywhere in the frame.

Reaching page 11+ would mean ~40 sequential `>` clicks *per download*, roughly
8,700 clicks for a full sweep — 12+ hours of pure navigation. Not viable.

**Therefore one search yields at most ~100 certificates (pages 1–10).**

To get more, don't fight the pager — **narrow the search so the whole result set
fits in 10 pages**, and run the script repeatedly. Everything lands in the same
folder and resume makes overlap free:

```bash
.venv/bin/python balady_certs.py --all --from 01/10/2026 --to 31/12/2026
.venv/bin/python balady_certs.py --all --from 01/01/2027 --to 31/03/2027
.venv/bin/python balady_certs.py --all --from 01/04/2027 --to 30/06/2027
```

Slice by expiry date range, by city, or by درجة التصنيف — whatever partitions
your target set into chunks under ~100. Check the reported page count: if it
says more than 10 pages, the slice is still too wide.

### 4.11 The results grid rebuilds after every download

### 4.11 The results grid rebuilds after every download

Pega re-renders the table each time, invalidating any cached element handle.
This is a non-issue in Playwright because **locators are lazy** — they re-query
the DOM on every use. The script re-resolves `.nth(i)` inside the loop:

```python
for i in range(want):
    btn = frame.locator("button:has-text('تنزيل')").nth(i)   # re-resolved each pass
```

---

## 5. Code walkthrough

```
main()                  parse CLI flags
└── run()
    ├── launch Chrome (channel="chrome", accept_downloads=True)
    ├── goto portal, wait for #PegaGadgetIfr
    ├── js_click() the "بحث متقدم" radio        ← sticky-header workaround (4.2)
    ├── select_dropdown() ×4                    ← resolved by Pega property (4.4)
    │     └── dropdown_index() → JS_FIELDS inventory
    ├── set_date()                              ← calendar navigation (4.7)
    ├── click بحث, wait for first تنزيل button
    └── loop: expect_download() → save_as(suggested_filename)
```

Helper functions:

- **`js_click(locator)`** — synthetic DOM click that ignores overlays.
- **`safe_click(locator)`** — real click, falling back to `js_click`.
- **`dropdown_index(frame, prop)`** — maps a Pega property to a DOM index.
- **`select_dropdown(frame, prop, text)`** — picks an option, then **verifies**
  the widget reads back the expected value and raises if not.
- **`set_date(frame, page, which, ddmmyyyy)`** — drives the calendar, then
  verifies the hidden input before continuing.
- **`dump_options(frame)`** — powers `--list-options`.

The design principle throughout: **never assume an action worked — read the
value back and fail loudly if it disagrees.** On any exception the script writes
`error.png` to the output directory so you can see what the page looked like.

---

## 6. Limitations

- **~100 certificates per search, maximum** — see §4.12. Slice the query and
  rerun to go beyond that.
- **Speed is capped by the server**, not the script — ~15 s per certificate,
  sequential. Parallelising it would mean hammering a public service, which is
  out of scope on purpose.
- **Failed rows are retried once**, then recorded as `FAILED` in `manifest.csv`.
  Rerunning the command retries only those (everything else is skipped).
- **Arabic text will not extract from the PDFs.** They are generated by PD4ML
  without a ToUnicode map, so `pdftotext` returns nothing useful. To get the data
  as text, either OCR the rendered pages, or use the **تصدير** (export) button on
  the results grid instead of downloading individual certificates.
- **Selectors are tied to the current portal build.** If Balady redesigns the
  form, `.dga-select`, the property ids, or the daterangepicker classes may
  change. `--list-options` and `--headed` are the debugging tools for that.

---

## 7. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `TimeoutError ... #PegaGadgetIfr` | Portal slow or down. Retry; raise `T_LOAD`. |
| `No dropdown with property 'X'` | Form changed. Run `--list-options` to see the real property ids. |
| `Option '...' not found under X` | Wrong spelling, or the cascade hasn't loaded. The error prints the available options — copy one exactly. |
| `Date StartDate should be ... but reads ''` | تطبيق wasn't pressed or the wrong cell was clicked. Re-run with `--headed` to watch. |
| Timeout waiting for `تنزيل` | Search returned nothing. Your filters may be too narrow — try without `--from`. |
| Download times out | Portal under load. Raise `T_DOWNLOAD` or increase `--delay`. |
| Everything fails at once | Check `error.png` in the output directory. |

To watch it work in real time:

```bash
.venv/bin/python balady_certs.py --headed --limit 1
```

---

## 8. Legal / etiquette

This is a **public, anonymous** government lookup service — the URL literally
contains `Anonymous`, and no login or credential is involved. The certificates
are published so that contractors' credentials can be verified.

Keep usage proportionate: the defaults download 5 files with a 2-second gap.
Don't remove `--delay` or loop this in a tight schedule. The portal is slow
because it does real work per request, and hammering a public ministry service
is both rude and a good way to get your IP blocked.

---

## 9. `qr_details.py` — reading the QR codes

Every certificate PDF has a small QR code in the bottom-left corner. It links to
a Balady page publishing the establishment's contact details. This script turns
those into a spreadsheet.

```bash
.venv/bin/python qr_details.py              # process ./pdf_files
.venv/bin/python qr_details.py --limit 5    # trial run
.venv/bin/python qr_details.py --show       # print each record as it goes
```

Output: **`pdf_files/qr_details.csv`**, one row per certificate:

| Column | Example |
|---|---|
| `uid` | `7042013313` — the company number starting with 7 |
| `facility_name` | شركة الإنشاء المدني للمقاولات |
| `owner_name` | ‹اسم المالك› |
| `phone` | `0512345678` |
| `email` | `owner@example.com` |
| `city` / `region` | الرياض / منطقة الرياض |
| `activity` | إنشاء محطات ومشاريع الصرف الصحي… |
| `cert_no`, `case_id`, `classification_type`, `qr_url`, `pdf_file` | provenance |

Resumable: rerunning skips PDFs already in the CSV. `--retry-failed` re-attempts
rows recorded as errors.

### How it works

**No browser.** Unlike `balady_certs.py`, this needs only one plain HTTP request
per certificate (~6 s each including the polite delay), so ~100 certificates
takes about 10 minutes.

1. **Extract the QR.** It is a real embedded image object in the PDF — typically
   120×120 RGB, under 1 KB — so `pdfimages` recovers it losslessly. Rendering
   the page instead does **not** work: at page resolution the code is too small
   for OpenCV to lock onto (`detectAndDecodeMulti` on a 200-dpi full page finds
   nothing). The script extracts all images and tries the small square ones,
   upscaling ×3 and ×6 if needed.

2. **Decode.** `cv2.QRCodeDetector`. The codes declare an ECI block OpenCV does
   not implement, so it logs `ECI is not supported properly` — decoding
   succeeds regardless, and the warning is muted.

   ```
   https://ccs.balady.gov.sa/prweb/PRAuth/QRCode/viewCertificateDetails/Q0NMLTkyNTIyNQ==
   ```
   The trailing segment is base64 — `Q0NMLTkyNTIyNQ==` → `CCL-925225`, the
   Pega case id.

3. **Fetch.** That URL answers **307** and redirects into a Pega harness. The
   redirect establishes a session, so the request must carry cookies — hence
   `http.cookiejar`; without it the second hop returns nothing useful.

4. **Parse.** Stripping tags yields only the page title — the data lives in
   embedded JavaScript, in two places:
   - `<div id='AJAXCT' data-json='…'>` → JSON with `CRorLICNumber`, `CaseID`,
     `ClassificationType`
   - a caption map holding the display values

   In that caption map, **the leading `$` is the only thing separating a value
   from its label**:
   ```
   "$CCPhoneNumber$pyCaption":"0512345678"     ← value
   "Phone number$pyCaption":"رقم الهاتف"        ← label
   ```
   The regex requires the `$`. Miss that and you harvest Arabic field labels
   instead of data.

5. **Cross-check.** The downloader names files `<certNo>_<uid>_…`, so the script
   compares the uid on the fetched page against the uid in the filename and
   warns on any mismatch — the same defence used in §4.10.

### A note on the data

These are real people's mobile numbers and personal email addresses. The portal
publishes them so contractor credentials can be verified, and the QR is printed
on the certificate for exactly that purpose — but treat the CSV accordingly, and
don't repost it somewhere it wasn't already public.

---

## 10. `make_excel.py` — CSV → Excel

```bash
.venv/bin/python make_excel.py                       # qr_details.csv -> qr_details.xlsx
.venv/bin/python make_excel.py --csv pdf_files/manifest.csv
.venv/bin/python make_excel.py --csv a.csv --out ~/Desktop/report.xlsx
```

Writes `pdf_files/qr_details.xlsx`: bilingual headers, frozen + filterable
header row, right-to-left sheet for Arabic, sized columns, clickable QR links.

### Why not just rename the .csv

Excel silently corrupts this data on open:

- **Saudi mobiles lose their leading zero.** `0512345678` becomes `512345678`.
- **10-digit company numbers flip to scientific notation** — `7042013313`
  renders as `7.04201E+09`.

The script writes those columns as real text cells (`number_format = "@"`),
which is the only reliable fix. Columns treated as text: `phone`, `fax`, `uid`,
`cert_no`, `mobile`.

Verified on the 100-row export: 100/100 phones still start with `0`, and every
phone cell is a Python `str` rather than an `int`.

`--ltr` switches the sheet back to left-to-right if you prefer.
