"""
pull.py — Download Notion pages into your configured folder, mirroring the page hierarchy.

Usage:
    python scripts/pull.py

Skips pages unchanged since the last pull (compared by Notion's last_edited_time).
Mirrors Notion's page tree as nested folders:

    <PAGES_DIR>/
      Root_Page.md
      Root_Page/
        Child_Page.md
        Child_Page/
          Grandchild.md

State is tracked in <PAGES_DIR>/.sync_state.json.

Configuration (in .env at repo root):
    PAGES_DIR=my-notion-pages   # folder name to store pages in

Requires:
    NOTION_API_KEY environment variable set to your Notion integration token.
"""

import asyncio
import json
import os
import re
from pathlib import Path
from notionary import Notionary
from tqdm import tqdm

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


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def slugify(title: str) -> str:
    title = re.sub(r"[^\w\s-]", "", title)
    title = re.sub(r"\s+", "_", title.strip())
    return title[:80] or "untitled"


def normalize_id(uid: str) -> str:
    return uid.replace("-", "")


async def fetch_all_pages_raw(http) -> list[dict]:
    """Fetch all accessible pages via Notion search API with full metadata."""
    pages = []
    cursor = None
    while True:
        body = {"filter": {"value": "page", "property": "object"}, "page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        response = await http.post("search", body)

        for item in response.get("results", []):
            if item.get("in_trash"):
                continue

            title = "Untitled"
            for prop in item.get("properties", {}).values():
                if prop.get("type") == "title":
                    title = "".join(
                        rt.get("plain_text", "") for rt in prop.get("title", [])
                    ) or "Untitled"
                    break

            parent = item.get("parent", {})
            parent_type = parent.get("type")
            parent_id_raw = parent.get("page_id") or parent.get("database_id")

            pages.append(
                {
                    "id": normalize_id(item["id"]),
                    "raw_id": item["id"],
                    "title": title,
                    "last_edited_time": item.get("last_edited_time", ""),
                    "parent_type": parent_type,
                    "parent_id": normalize_id(parent_id_raw) if parent_id_raw else None,
                }
            )

        if not response.get("has_more"):
            break
        cursor = response.get("next_cursor")

    return pages


def compute_paths(pages: list[dict]) -> dict[str, str]:
    """Map page_id → relative filepath mirroring Notion hierarchy.

    Example:
        Projects            → Projects.md
        Web Project         → Projects/Web_Project.md   (child of Projects)
        Task List           → Projects/Web_Project/Task_List.md
    """
    page_by_id = {p["id"]: p for p in pages}
    accessible_ids = set(page_by_id)
    path_cache: dict[str, str] = {}

    def get_path(page_id: str, visited: frozenset = frozenset()) -> str:
        if page_id in path_cache:
            return path_cache[page_id]
        if page_id in visited:
            # Cycle guard: treat as root
            path = slugify(page_by_id[page_id]["title"]) + ".md"
            path_cache[page_id] = path
            return path

        page = page_by_id[page_id]
        slug = slugify(page["title"])
        parent_id = page.get("parent_id")

        if (
            page["parent_type"] != "page_id"
            or not parent_id
            or parent_id not in accessible_ids
        ):
            path = slug + ".md"
        else:
            parent_path = get_path(parent_id, visited | {page_id})
            parent_dir = parent_path[:-3]  # "Projects.md" → "Projects"
            path = parent_dir + "/" + slug + ".md"

        path_cache[page_id] = path
        return path

    paths = {p["id"]: get_path(p["id"]) for p in pages}

    # Resolve duplicate paths (pages with identical titles at same level)
    seen: dict[str, str] = {}  # path → page_id
    for pid, path in list(paths.items()):
        if path in seen:
            # Append short ID suffix to make unique
            page = page_by_id[pid]
            base = path[:-3]  # strip .md
            new_path = f"{base}_{pid[:6]}.md"
            paths[pid] = new_path
            path_cache[pid] = new_path
        else:
            seen[path] = pid

    return paths


async def pull():
    state = load_state()
    PAGES_DIR.mkdir(parents=True, exist_ok=True)

    async with Notionary() as notion:
        print("Fetching page list...")
        pages = await fetch_all_pages_raw(notion._http)

    if not pages:
        print("No pages found. Make sure your integration has access to pages.")
        return

    paths = compute_paths(pages)
    to_download = []

    for page in pages:
        pid = page["id"]
        rel_path = paths[pid]
        filepath = PAGES_DIR / rel_path
        prev = state.get(pid, {})
        if (
            prev.get("notion_last_edited") == page["last_edited_time"]
            and filepath.exists()
            and prev.get("filepath") == rel_path
        ):
            continue
        to_download.append((page, rel_path, filepath, prev))

    skipped = len(pages) - len(to_download)
    print(f"Found {len(pages)} page(s) — {len(to_download)} to download, {skipped} unchanged.")

    if not to_download:
        print("Nothing to do.")
        return

    updated = 0
    with tqdm(total=len(to_download), unit="page", dynamic_ncols=True) as bar:
        for page, rel_path, filepath, prev in to_download:
            pid = page["id"]
            bar.set_description(rel_path[:50])

            # Move file if its position in the tree changed
            old_path = prev.get("filepath")
            if old_path and old_path != rel_path:
                old_file = PAGES_DIR / old_path
                if old_file.exists():
                    old_file.unlink()
                    try:
                        old_file.parent.rmdir()
                    except OSError:
                        pass
                    tqdm.write(f"  moved:   {old_path} → {rel_path}")

            # Download content
            async with Notionary() as notion:
                p = await notion.pages.from_id(page["raw_id"])
                content = await p.get_markdown()

            # Write file
            filepath.parent.mkdir(parents=True, exist_ok=True)
            frontmatter = f"---\nnotion_id: {page['raw_id']}\ntitle: {page['title']}\n---\n\n"
            filepath.write_text(frontmatter + content, encoding="utf-8")

            # Record state immediately (survives interruption)
            state[pid] = {
                "filepath": rel_path,
                "notion_last_edited": page["last_edited_time"],
                "local_mtime": filepath.stat().st_mtime,
                "title": page["title"],
            }
            save_state(state)

            updated += 1
            bar.update(1)

    print(f"\nDone. {updated} downloaded, {skipped} unchanged.")


if __name__ == "__main__":
    asyncio.run(pull())
