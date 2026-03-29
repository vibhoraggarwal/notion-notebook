"""
push.py — Upload locally edited or newly created markdown files to Notion.

Usage:
    python scripts/push.py              # push all changed/new pages
    python scripts/push.py "filename"   # push one file by name (without .md)

Behaviour:
  - Files with a notion_id in frontmatter: pushed only if locally modified.
  - Files WITHOUT a notion_id: treated as new pages and created in Notion.
      - Root-level files (e.g. hello.md) are created at workspace level.
      - Files in a subfolder (e.g. hello/world.md) require hello.md to already
        exist AND have a notion_id — push hello.md first if it doesn't.

The folder structure mirrors Notion's page hierarchy:
    hello.md              → top-level page "hello"
    hello/world.md        → "world" nested under "hello"

After creating a page, the local file's frontmatter is updated with its notion_id.

Configuration (in .env at repo root):
    PAGES_DIR=my-notion-pages

Requires:
    NOTION_API_KEY environment variable set to your Notion integration token.
"""

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from notionary import Notionary
from notionary.page import mapper as page_mapper
from notionary.page.schemas import PageDto
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent))
from weather import apply_weather, load_weather_config

REPO_ROOT = Path(__file__).parent.parent


def _load_dotenv():
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()
PAGES_DIR = REPO_ROOT / "notebook" / os.environ.get("PAGES_DIR", "pages")
STATE_FILE = PAGES_DIR / ".sync_state.json"


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def normalize_id(uid: str) -> str:
    return uid.replace("-", "")


# ---------------------------------------------------------------------------
# File parsing / frontmatter helpers
# ---------------------------------------------------------------------------

def title_from_filename(path: Path) -> str:
    return path.stem.replace("_", " ")


def parse_file(path: Path) -> dict:
    """Return dict with keys: notion_id (str|None), title (str), content (str)."""
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        return {
            "notion_id": None,
            "title": title_from_filename(path),
            "content": text.strip(),
        }

    fm = match.group(1)
    content = text[match.end():].strip()

    id_match = re.search(r"^notion_id:\s*(.+)$", fm, re.MULTILINE)
    title_match = re.search(r"^title:\s*(.+)$", fm, re.MULTILINE)

    return {
        "notion_id": id_match.group(1).strip() if id_match else None,
        "title": title_match.group(1).strip() if title_match else title_from_filename(path),
        "content": content,
    }


def write_notion_id_to_frontmatter(path: Path, notion_id: str, title: str):
    """Inject notion_id into the file's frontmatter (adds frontmatter if absent)."""
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if match:
        fm = match.group(1)
        body = text[match.end():]
        new_text = f"---\nnotion_id: {notion_id}\n{fm}\n---\n{body}"
    else:
        new_text = f"---\nnotion_id: {notion_id}\ntitle: {title}\n---\n\n{text}"
    path.write_text(new_text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Parent file resolution
# ---------------------------------------------------------------------------

def get_parent_file(filepath: Path) -> Path | None:
    """Return the .md file that should be the Notion parent of filepath, or None.

    hello.md              → None  (root level)
    hello/world.md        → hello.md
    hello/world/deep.md   → hello/world.md
    """
    rel = filepath.relative_to(PAGES_DIR)
    if rel.parent == Path("."):
        return None
    parent_name = rel.parent.name + ".md"
    parent_dir = rel.parent.parent
    candidate = PAGES_DIR / parent_dir / parent_name
    return candidate


# ---------------------------------------------------------------------------
# Notion API helpers
# ---------------------------------------------------------------------------

async def create_notion_page(http, title: str, parent_page_id: str | None) -> str:
    """Create a new Notion page. Returns the new page's raw ID string."""
    parent = {"page_id": parent_page_id} if parent_page_id else {"workspace": True}
    body = {
        "parent": parent,
        "properties": {
            "title": {"title": [{"text": {"content": title}}]}
        },
    }
    response = await http.post("pages", data=body)
    return response["id"]


# ---------------------------------------------------------------------------
# Push actions
# ---------------------------------------------------------------------------

async def create_new_page(path: Path, info: dict, state: dict, http) -> bool:
    """Create a brand-new page in Notion. Returns True on success."""
    parent_file = get_parent_file(path)

    if parent_file is not None:
        if not parent_file.exists():
            rel_parent = parent_file.relative_to(PAGES_DIR)
            rel_self = path.relative_to(PAGES_DIR)
            print(f"  warn:    {rel_self} — parent page '{rel_parent}' does not exist locally.")
            print(f"           Create {rel_parent} first, then push it before pushing this file.")
            return False

        parent_info = parse_file(parent_file)
        if not parent_info["notion_id"]:
            rel_parent = parent_file.relative_to(PAGES_DIR)
            rel_self = path.relative_to(PAGES_DIR)
            print(f"  warn:    {rel_self} — parent '{rel_parent}' has no notion_id yet.")
            print(f"           Push {rel_parent} first so Notion knows where to nest this page.")
            return False

        parent_notion_id = parent_info["notion_id"]
    else:
        parent_notion_id = None  # workspace root

    new_raw_id = await create_notion_page(http, info["title"], parent_notion_id)

    # Set content on the newly created page
    dto_response = await http.get(f"pages/{new_raw_id}")
    dto = PageDto.model_validate(dto_response)
    page = page_mapper.to_page(dto, http)
    if info["content"]:
        await page.replace(info["content"])

    # Write notion_id back into the local file
    write_notion_id_to_frontmatter(path, new_raw_id, info["title"])

    pid = normalize_id(new_raw_id)
    rel = path.relative_to(PAGES_DIR)
    state[pid] = {
        "filepath": str(rel),
        "notion_last_edited": None,   # will be refreshed on next pull
        "local_mtime": path.stat().st_mtime,
        "title": info["title"],
    }
    save_state(state)
    return True


async def update_existing_page(path: Path, info: dict, state: dict) -> bool:
    """Update an existing page if locally modified. Returns True if pushed."""
    pid = normalize_id(info["notion_id"])
    current_mtime = path.stat().st_mtime
    page_state = state.get(pid, {})

    if page_state.get("local_mtime") == current_mtime:
        return False  # unchanged

    async with Notionary() as notion:
        page = await notion.pages.from_id(info["notion_id"])
        await page.replace(info["content"])

    if pid not in state:
        state[pid] = {}
    state[pid]["local_mtime"] = path.stat().st_mtime
    save_state(state)
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def push(target: str | None = None):
    state = load_state()

    if target:
        name = target if target.endswith(".md") else target + ".md"
        matches = list(PAGES_DIR.rglob(name))
        if not matches:
            print(f"File not found in {PAGES_DIR.name}/: {name}")
            return
        files = matches
    else:
        files = [
            f for f in PAGES_DIR.rglob("*.md")
            if f != STATE_FILE and f.suffix == ".md"
        ]

    if not files:
        print("No .md files found. Run pull.py first.")
        return

    # Sort so shallower paths (parents) are processed before deeper ones (children)
    files = sorted(files, key=lambda f: len(f.parts))

    weather_config = load_weather_config()
    tz = os.environ.get("WEATHER_TZ", "Europe/Berlin")

    created = pushed = skipped = 0

    async with Notionary() as notion:
        with tqdm(total=len(files), unit="page", dynamic_ncols=True) as bar:
            for f in files:
                rel = f.relative_to(PAGES_DIR)
                bar.set_description(str(rel)[:50])

                # Auto-refresh weather for all saved configs on this file
                wc_list = weather_config.get(str(rel), [])
                for wc in wc_list:
                    try:
                        await apply_weather(
                            f,
                            wc.get("start"),
                            wc.get("end"),
                            wc["lat"],
                            wc["lon"],
                            tz,
                            wc.get("resolved_city"),
                        )
                        label = wc.get("resolved_city") or "default"
                        tqdm.write(f"  weather: {rel} ({label})")
                    except Exception as e:
                        tqdm.write(f"  weather error ({rel}): {e}")

                info = parse_file(f)
                try:
                    if info["notion_id"] is None:
                        ok = await create_new_page(f, info, state, notion._http)
                        if ok:
                            tqdm.write(f"  created: {rel}")
                            created += 1
                    else:
                        changed = await update_existing_page(f, info, state)
                        if changed:
                            tqdm.write(f"  pushed:  {rel}")
                            pushed += 1
                        else:
                            skipped += 1
                except Exception as e:
                    tqdm.write(f"  error ({rel}): {e}")
                bar.update(1)

    print(f"\nDone. {created} created, {pushed} pushed, {skipped} unchanged.")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(push(target))
