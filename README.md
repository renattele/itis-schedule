# ITIS Schedule → iCal Generator

CLI application that fetches the [KFU ITIS schedule](https://docs.google.com/spreadsheets/d/13CqvyFsOa5Z5LYCfMCz4IyAnuTIcjYqI0ARgt8-5MpQ) from Google Sheets and generates `.ics` (iCal) calendar files for every student group.

## Quick Start

### Run with Docker

```bash
docker build -t itis-schedule .
docker run --rm -v $(pwd)/calendars:/app/calendars itis-schedule
```

### Run with Python

```bash
pip install -r requirements.txt
python -m src.main --output-dir ./calendars
```

## CLI Options

| Flag | Default | Description |
|------|---------|-------------|
| `--spreadsheet-id` | `13CqvyFsOa5Z5LYCfMCz4IyAnuTIcjYqI0ARgt8-5MpQ` | Google Sheets document ID |
| `--gid` | `0` | Sheet tab ID |
| `--output-dir` | `./calendars` | Output directory for `.ics` files |
| `--semester-start` | `2026-02-09` | Semester start date (`YYYY-MM-DD`) |
| `--semester-end` | `2026-06-06` | Semester end date (`YYYY-MM-DD`) |

## GitHub Actions

The included workflow (`.github/workflows/generate.yml`) runs **daily at 09:00 Moscow time** and can also be triggered manually. It:

1. Builds the Docker image
2. Generates `.ics` files for all groups
3. Commits updated calendars back to the repository

## Project Structure

```
├── .github/workflows/generate.yml   # Automated schedule generation
├── Dockerfile                       # Container definition
├── requirements.txt                 # Python dependencies
├── src/
│   ├── __init__.py
│   ├── fetcher.py                   # Google Sheets CSV downloader
│   ├── parser.py                    # Schedule CSV parser
│   ├── generator.py                 # iCal file generator
│   └── main.py                      # CLI entry point
└── calendars/                       # Generated .ics files (gitignored locally)
```

## How to Subscribe

After the workflow runs, each group's `.ics` file is available at:

```
https://raw.githubusercontent.com/<owner>/<repo>/main/calendars/<group>.ics
```

You can add this URL as a calendar subscription in Google Calendar, Apple Calendar, or any iCal-compatible client.
