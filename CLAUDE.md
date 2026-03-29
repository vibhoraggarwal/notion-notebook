# notion-notebook

Local markdown mirror of a Notion workspace. Pages live in `notebook/<PAGES_DIR>/` as `.md` files mirroring Notion's page hierarchy as nested folders.

## Key commands

```bash
make pull                    # download all Notion pages locally
make push                    # upload locally changed pages to Notion
make weather                 # update weather on default page (from .env)
make install                 # pip install -r requirements.txt into active Python
make setup                   # create .env from .env.example
make help                    # list all targets
make help-weather            # detailed weather usage
```

## Folder structure

```
notebook/                    # gitignored root for all local Notion content
  <PAGES_DIR>/               # user subfolder set in .env (e.g. vibhor-notion/)
    .sync_state.json         # tracks Notion last_edited_time + local file mtimes
    .weather_config.json     # per-file weather auto-refresh configs
    Projects.md              # root-level Notion page
    Projects/
      Web_Project.md         # child of Projects
scripts/
  pull.py                    # sync down from Notion
  push.py                    # sync up to Notion (also auto-refreshes weather)
  weather.py                 # update weather tables in local files
  agent.py                   # natural language agent for the notebook
notionary/                   # git submodule (vibhoraggarwal fork)
.env                         # gitignored user config
.env.example                 # template
requirements.txt             # notionary, tqdm, anthropic
```

## Sync behaviour

- **pull**: skips pages unchanged since last pull (compares `last_edited_time`)
- **push**: skips files whose mtime hasn't changed since last pull/push
- **weather**: writes to local file only — run `make push` after to sync to Notion
- **push + weather**: if a file has a saved weather config (`--remember`), push auto-refreshes weather before uploading

## Frontmatter format

Every synced page has a YAML frontmatter block — do not remove it:

```markdown
---
notion_id: abc-123-...
title: Page Title
---

# Content here
```

Files without `notion_id` are treated as new pages and created in Notion on push. For files in subdirectories, the parent `.md` file must exist and have a `notion_id` first.

## Weather workflow

```bash
# Add weather + remember for auto-refresh on push
make weather PAGE="My Page" FROM=2026-04-03 TO=2026-04-06 CITY=Stuttgart REMEMBER=1

# Multiple cities on the same page
make weather PAGE="My Page" FROM=2026-04-03 TO=2026-04-06 REMEMBER=1          # default city from .env
make weather PAGE="My Page" FROM=2026-04-03 TO=2026-04-06 CITY=Berlin REMEMBER=1
```

Weather uses Open-Meteo (free, no API key). City names are geocoded automatically.

## Environment variables (.env)

```
PAGES_DIR=vibhor-notion       # subfolder inside notebook/
WEATHER_PAGE=Daily Notes      # default page for weather
WEATHER_CITY=Stuttgart        # default city label
WEATHER_LAT=48.78
WEATHER_LON=9.18
WEATHER_TZ=Europe/Berlin
```

