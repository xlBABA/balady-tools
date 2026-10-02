# balady-tools

Tools for the Saudi Balady portal's public contractor-classification lookup
(**التحقق من شهادة التصنيف - التأهيل**).

They automate a public, anonymous government lookup: search for classified
contractors in a city, download their classification certificates as PDFs, read
the QR code printed on each one, and collect the published contact details into
a spreadsheet.

Service: <https://apps.balady.gov.sa/Eservices/MServices/Home/Anonymous?id=190>

---

## Two directories

| Directory | What it is |
|---|---|
| **[`new-tool/`](new-tool/)** | **Start here.** One command does everything: pick a city → download PDFs → read QRs → produce an Excel contact list. |
| [`old-tools/`](old-tools/) | The three separate scripts the pipeline is built from. Use these if you want to run a single stage on its own. |

`new-tool/` vendors its own copies of two scripts from `old-tools/`, so each
directory runs standalone.

---

## Quick start

```bash
git clone https://github.com/xlBABA/balady-tools.git
cd balady-tools/new-tool

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

.venv/bin/python run.py
```

It asks which city you want, then runs the whole pipeline (~35 minutes for a
full city) and writes `contacts_<date>.xlsx`.

Also needs **Google Chrome** and **`pdfimages`** (`poppler-utils`).

---

## What the output looks like

| اسم المنشأة / Company | رقم الهاتف / Phone | الرقم الوطني / Company no. | تاريخ الانتهاء / Expiry | اسم المالك / Owner | البريد الإلكتروني / Email |
|---|---|---|---|---|---|
| شركة الندى الوطنية | 0512345678 | 7002530819 | 23/11/2026 | ‹اسم المالك› | ‹email› |

### Choosing a city, and other options

```bash
.venv/bin/python run.py                        # asks you to pick a city
.venv/bin/python run.py --city جدة              # single-word name
.venv/bin/python run.py --city "مكة المكرمة"    # QUOTE names containing a space
.venv/bin/python run.py --limit 5              # quick ~2-minute trial
.venv/bin/python run.py --folder makkah        # name the output folder
.venv/bin/python run.py --mobiles-only         # keep only 05x phone numbers
.venv/bin/python run.py --skip-download        # reuse PDFs, redo QR + Excel
```

| Flag | Default | What it does |
|---|---|---|
| `--city` | *prompts you* | which city to search (220 available) |
| `--limit` | `0` | how many certificates; `0` = as many as reachable (~100) |
| `--folder` | today's date | output folder name |
| `--mobiles-only` | off | drop rows whose phone does not start with `05` |
| `--delay` | `2.0` | seconds between downloads — don't lower it |
| `--skip-download` | off | skip straight to the QR + Excel steps |

**Quote any city name with a space** — `"مكة المكرمة"`, `"المدينة المنورة"`,
`"حفر الباطن"`, `"خميس مشيط"`. Without quotes the shell splits it in two and
argparse rejects the leftover word. Picking from the menu avoids this entirely.

**Output folders are named by date.** Running two cities on the same day would
put both in the same folder — use `--folder` for the second.

**Everything resumes.** Ctrl-C any time; rerun the same command and it skips
PDFs already downloaded and contacts already fetched.

---

## Two things to know before you use this

**~100 certificates per search.** Not a limitation of these tools — the portal
resets its results grid to page 1 after *every* download, and its pager only
exposes a 10-page window. To collect more, narrow the search (by expiry date
range or city) and run again. The full explanation, with the experiments that
established it, is in [`old-tools/TECHNICAL.md`](old-tools/TECHNICAL.md) §4.12.

**The output contains personal data.** The certificates and the QR pages publish
business owners' names, personal mobile numbers and personal email addresses.
The portal makes these public so contractor credentials can be verified — that
is what the QR on the certificate is *for*. That does not make them yours to
republish. **No harvested data is committed to this repository**, and
`.gitignore` is set up to keep it that way. Keep your own output local.

**Be polite to the service.** Each PDF is rendered on demand by the server. The
default 2-second delay between downloads is already brisk for ~100 sequential
requests; don't lower it, and don't run several copies in parallel.

---

## Technical notes

The portal is a Pega BPM app with a number of non-obvious traps — an iframe that
500s if you load it directly, a sticky header that swallows clicks, dropdowns
whose DOM order doesn't match their visual order, and a results grid that
silently hands you the wrong row if you address it by position.

All of it is written up in [`old-tools/TECHNICAL.md`](old-tools/TECHNICAL.md),
including the bugs that were found and how they were caught.

## License

MIT — see [LICENSE](LICENSE).
