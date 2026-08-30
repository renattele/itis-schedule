# ITIS Schedule → iCal Generator

CLI application that fetches the [KFU ITIS schedule](https://docs.google.com/spreadsheets/d/12m_Ze1NOnVvdVuSDY5bj0v4r24xLY5RhtuBxNjS26yQ) from Google Sheets and generates `.ics` (iCal) calendar files for every student group.

Per-student calendars drop unchosen electives using the [4th-year course distribution](https://docs.google.com/spreadsheets/d/1ylZLNeuGEpb_7lVqtRlOfs6ngj_c977Zgt5XKZf_aSc) (main and humanitarian blocks; spring-semester columns are skipped).

## Quick Start

### Run with Docker

```bash
docker build -t itis-schedule .
docker run --rm \
  -v $(pwd)/calendars:/app/calendars \
  -v $(pwd)/overrides.json:/app/overrides.json \
  itis-schedule \
  --split-types \
  --overrides /app/overrides.json
```

### Overrides Format

You can override event parameters using a JSON file where keys are regular expressions matching the subject name:

```json
{
  "Технологии разработки ПО.*Kotlin.*": {
    "subject": "KMP Development",
    "link": "https://example.com/new-kotlin-link",
    "notes": "Custom notes for this subject"
  }
}
```

## CLI Options

| Flag | Default | Description |
|------|---------|-------------|
| `--spreadsheet-id` | `12m_Ze1NOnVvdVuSDY5bj0v4r24xLY5RhtuBxNjS26yQ` | Google Sheets document ID |
| `--gid` | `0` | Sheet tab ID |
| `--output-dir` | `./calendars` | Output directory for `.ics` files |
| `--semester-start` | `2026-09-01` | Semester start date (`YYYY-MM-DD`) |
| `--semester-end` | `2026-12-31` | Semester end date (`YYYY-MM-DD`) |
| `--overrides` | | Path to JSON file with event overrides (regex keys) |
| `--student-choices` | `student_choices.json` | Optional local overlay of per-student electives (skipped if the file is missing) |
| `--choices-spreadsheet-id` | `1ylZLNeuGEpb_7lVqtRlOfs6ngj_c977Zgt5XKZf_aSc` | Google Sheets ID with the 4th-year elective distribution |
| `--choices-gid` | all tabs | Sheet tab gid to load; pass multiple times. Default discovers every tab |

## GitHub Actions

The included workflow (`.github/workflows/generate.yml`) runs **every 5 hours** and can also be triggered manually. It:

1. Builds the Docker image
2. Runs tests
3. Generates `.ics` files for all groups
4. Publishes them to the `calendars` branch

## Project Structure

```
├── .github/workflows/generate.yml   # Automated schedule generation
├── Dockerfile                       # Container definition
├── requirements.txt                 # Python dependencies
├── src/
│   ├── __init__.py
│   ├── fetcher.py                   # Google Sheets CSV downloader
│   ├── parser.py                    # Schedule CSV parser
│   ├── electives.py                 # Elective distribution sync + matching
│   ├── generator.py                 # iCal file generator
│   └── main.py                      # CLI entry point
└── calendars/
    ├── groups/
    │   ├── unified/
    │   ├── lectures/
    │   └── practices/
    └── students/
        ├── unified/
        ├── lectures/
        └── practices/
```

## How to Subscribe

After the workflow runs, each group's unified `.ics` file is available at:

```
https://raw.githubusercontent.com/<owner>/<repo>/calendars/groups/unified/<group>.ics
```

Student calendars are available at:

```
https://raw.githubusercontent.com/<owner>/<repo>/calendars/students/unified/<group>_<student>.ics
```

You can add this URL as a calendar subscription in Google Calendar, Apple Calendar, or any iCal-compatible client.
