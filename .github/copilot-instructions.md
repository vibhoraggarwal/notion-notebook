# Copilot instructions — notion-notebook

This repo is a local markdown mirror of a Notion workspace. Notion pages are stored as `.md` files under `notebook/<PAGES_DIR>/`, mirroring the page hierarchy as nested folders.

## Project structure

- `notebook/` — gitignored, contains all synced Notion pages as markdown files
- `scripts/pull.py` — downloads pages from Notion, mirrors hierarchy as folders
- `scripts/push.py` — uploads locally changed files to Notion; auto-refreshes weather for remembered pages
- `scripts/weather.py` — fetches weather from Open-Meteo and writes tables into local `.md` files
- `scripts/agent.py` — natural language agent using the Anthropic API
- `notionary/` — git submodule, Python library wrapping the Notion API
- `.env` — gitignored user config (PAGES_DIR, WEATHER_* variables)

## Markdown file format

Every synced page has YAML frontmatter:

```markdown
---
notion_id: abc-123-...
title: Page Title
---

# Content here
```

Files without `notion_id` are new pages — they get created in Notion on the next push. A file in a subdirectory requires its parent `.md` to exist and have a `notion_id`.

## Key conventions

- All scripts are async Python using `asyncio`
- `notionary` is the Notion API client — all Notion interactions go through it or its raw `_http` client
- `.sync_state.json` in the pages folder tracks `last_edited_time` (Notion) and `local_mtime` (filesystem) for change detection
- `.weather_config.json` stores per-file weather configs as a list (multiple cities/date ranges per file supported)
- Weather sections in pages use the anchor pattern `## Weather · <city> <date> → <date>` for in-place updates
- `slugify()` in pull.py converts Notion page titles to safe filenames
- All scripts load `.env` via a small inline `_load_dotenv()` function (no python-dotenv dependency)
- `tqdm` is used for progress bars in pull/push; use `tqdm.write()` for messages inside bar loops

## Make targets

```
make install    — python -m pip install -r requirements.txt
make setup      — cp .env.example .env
make pull       — sync down from Notion
make push       — sync up to Notion
make weather    — update weather in local file
make help       — list targets
make help-weather — detailed weather usage
```
