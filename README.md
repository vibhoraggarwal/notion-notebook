# notion-workspace

Local markdown mirror of my Notion workspace. Pull pages down, edit locally, push changes back. Syncs only what has changed.

## Setup

### 1. Get a Notion API key

1. Go to [notion.so/my-integrations](https://www.notion.so/my-integrations)
2. Click **New integration**, give it a name, select your workspace
3. Copy the **Internal Integration Token** (starts with `secret_`)

### 2. Set the environment variable

```bash
export NOTION_API_KEY=secret_your_token_here
```

Add this to `~/.bashrc` or `~/.zshrc` to persist across sessions.

### 3. Give the integration access to your pages

In Notion, open any page → `...` menu (top right) → **Connect to** → select your integration.

Do this for a top-level page to grant access to all its children automatically.

### 4. Create your `.env` file

```bash
cp .env.example .env
```

Set `PAGES_DIR` to your own subfolder name. Pages will be stored at `notebook/<PAGES_DIR>/`:

```
PAGES_DIR=vibhor-notion   # → notebook/vibhor-notion/
```

The `notebook/` root is gitignored for everyone. Your subfolder inside it is yours.

### 5. Install dependencies

```bash
pip install -r requirements.txt
```

Or, to use the bundled submodule fork instead of PyPI notionary:

```bash
pip install -e ./notionary
pip install tqdm
```

---

## Workflow

### Pull — download pages from Notion

```bash
python scripts/pull.py
```

- Fetches all pages the integration can access
- Mirrors Notion's page hierarchy as nested folders
- **Skips pages unchanged since the last pull** (compares Notion's `last_edited_time`)
- Saves sync state to `notebook/<PAGES_DIR>/.sync_state.json`

### Edit locally

Open any `.md` file in `notebook/<PAGES_DIR>/` and edit freely. The YAML block at the top tracks the Notion page ID — don't remove it.

```markdown
---
notion_id: abc123-...
title: My Page Title
---

# My Page Title

Edit content here...
```

### Push — upload changes back to Notion

```bash
# Push all locally changed files
python scripts/push.py

# Push a specific file (anywhere in the tree)
python scripts/push.py "My_Page_Title"
```

**Skips files whose modification time hasn't changed** since the last pull or push — so running push after a fresh pull with no edits does nothing.

---

## Folder structure

Notion's page hierarchy is mirrored as nested folders:

```
Notion:                          notebook/vibhor-notion/   (example PAGES_DIR)
  Projects                  →     Projects.md
    Web Project             →     Projects/Web_Project.md
      Task List             →     Projects/Web_Project/Task_List.md
  Journal                   →     Journal.md
    2026-03-29              →     Journal/2026-03-29.md
```

If a page moves in Notion (different parent), pull detects this and moves the local file accordingly.

---

## Repository structure

```
.env                        # Your config (gitignored) — set PAGES_DIR here
.env.example                # Template to copy from
requirements.txt            # Python dependencies (notionary, tqdm)
notebook/                   # Gitignored root for all Notion content
  <PAGES_DIR>/              # Your subfolder (set in .env), e.g. vibhor-notion/
    .sync_state.json        # Tracks last_edited_time and file mtimes (don't edit)
scripts/
  pull.py                   # Download pages from Notion
  push.py                   # Upload local edits back to Notion
notionary/                  # notionary library (git submodule, vibhoraggarwal fork)
```

---

## Writing your own data-injection scripts

The `notionary` API for appending data to a page:

```python
import asyncio
from notionary import Notionary

async def main():
    async with Notionary() as notion:
        page = await notion.pages.find("Daily Notes")
        await page.append("## Weather\n- Temp: 22°C\n- Condition: Sunny")

asyncio.run(main())
```

Use `append()` to add to the end, `replace()` to overwrite the full content.
