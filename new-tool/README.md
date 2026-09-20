# Balady pipeline — one command

Downloads contractor certificates for a city, reads the QR code on each one,
and produces a clean Excel contact list.

```bash
cd ~/Downloads/newtool
.venv/bin/python run.py
```

It asks which city you want, then does everything else by itself.

---

## What happens

| Step | What it does | Time |
|---|---|---|
| 0 | asks for the city (menu of 50, or type any name) | — |
| 1 | creates a folder named with today's date, e.g. `2026-09-20/` | — |
| 2 | downloads the certificate PDFs into it | ~25 min |
| 3 | reads every PDF's QR code, fetches the contact details | ~10 min |
| 4 | writes `contacts_<date>.xlsx` | 1 sec |

Total ≈ 35 minutes for a full ~100-certificate city.

## The Excel file

Exactly five columns, in this order:

| اسم المنشأة / Company | رقم الهاتف / Phone | الرقم الوطني / Company no. | اسم المالك / Owner | البريد الإلكتروني / Email |
|---|---|---|---|---|
| شركة الندى الوطنية | 0512345678 | 7002530819 | ‹اسم المالك› | owner@example.com |

Phone and company number are stored as **text**, so Excel cannot eat the leading
zero of `05...` or turn `7002530819` into `7.00253E+09`. Sheet is right-to-left,
header is frozen and filterable.

## Options

```bash
.venv/bin/python run.py                      # ask for the city, do everything
.venv/bin/python run.py --city جدة            # skip the question
.venv/bin/python run.py --limit 5            # small trial
.venv/bin/python run.py --mobiles-only       # drop any phone not starting 05
.venv/bin/python run.py --folder riyadh_run  # name the folder yourself
.venv/bin/python run.py --skip-download      # reuse PDFs already there, redo QR + Excel
```

| Flag | Default | Meaning |
|---|---|---|
| `--city` | *asks* | المدينة |
| `--limit` | `0` | how many certificates; 0 = as many as reachable (~100) |
| `--folder` | today's date | output folder name |
| `--mobiles-only` | off | keep only rows whose phone starts with `05` |
| `--delay` | `2.0` | seconds between downloads |
| `--skip-download` | off | start at the QR step |

## Good to know

- **Safe to interrupt.** Ctrl-C any time. Every stage resumes: rerun the same
  command and it skips PDFs already downloaded and contacts already fetched.
- **Partial failures don't stop it.** If 3 certificates out of 100 fail, the
  pipeline carries on and you still get an Excel with the other 97.
- **~100 per city per run** is the portal's ceiling, not this tool's. It resets
  its results grid to page 1 after every download and only exposes 10 pages.
  To get more, run again with a narrower date range — see `../test3/README.md`
  §4.12 for the full explanation.
- **One folder per day.** Running twice on the same day reuses that day's
  folder. If you want a second city kept separate, use `--folder`.
- **This directory is self-contained.** It has its own `.venv` and its own copy
  of the two worker scripts, so nothing here affects `~/Downloads/test3`.

## Files

| File | What |
|---|---|
| `run.py` | the pipeline — this is the one you run |
| `balady_certs.py` | stage 1, downloads PDFs (copy from test3) |
| `qr_details.py` | stage 2, reads QRs (copy from test3) |
| `requirements.txt` | pinned deps |
| `.venv/` | environment |
| `<date>/` | output: PDFs, `manifest.csv`, `qr_details.csv`, `contacts_<date>.xlsx` |

## Rebuilding from scratch

```bash
cd ~/Downloads/newtool
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Also needs `pdfimages` (poppler-utils) and Google Chrome, both already present.

## Etiquette

Public, anonymous government service — but it renders each PDF on demand. Keep
`--delay` at 2s or higher and don't run several copies at once. The CSV/Excel
contain real people's mobile numbers and personal emails; treat them accordingly.
