"""
deploy_root.py
Root-folder deployment (BepInEx, UE5, Mewgenics, Bannerlord, KCD2, BG3).

Extracted from deploy.py during the 2026-04 refactor. No behaviour changes.
"""

from __future__ import annotations

import concurrent.futures
import os
import shutil
import stat as _stat
import time as _time
from pathlib import Path

from Utils.app_log import safe_log as _safe_log
from Utils.deploy_shared import (
    LinkMode,
    _deploy_workers,
    _path_under_root,
    _resolve_root_path,
    _transfer,
)


# Name of the sibling directory used to back up pre-existing root files.
_ROOT_BACKUP_NAME = "Root_Backup"
# Name of the log file written next to Root_Folder/ recording what was placed.
_ROOT_LOG_NAME    = "root_folder_deployed.txt"


def deploy_root_folder(
    root_folder_dir: Path,
    game_root: Path,
    mode: LinkMode = LinkMode.HARDLINK,
    log_fn=None,
) -> int:
    """Transfer files from root_folder_dir into game_root.

    root_folder_dir — Profiles/<game>/Root_Folder/
    game_root       — the game's install directory (the root, not Data/)
    mode            — transfer method (HARDLINK / SYMLINK / COPY)

    Behaviour:
      - If root_folder_dir is empty or missing, does nothing and returns 0.
      - For each file that already exists in game_root, the existing file is
        moved to a sibling Root_Backup/ directory (preserving relative paths)
        before the mod file is transferred in.
      - A log file (root_folder_deployed.txt) is written next to Root_Folder/
        listing every relative path that was successfully placed.  This log is
        consumed by restore_root_folder() to undo the operation.

    Returns the number of files transferred.
    """
    _log = _safe_log(log_fn)

    if not root_folder_dir.is_dir():
        return 0

    # Collect all source files first; bail early if none.
    sources: list[tuple[Path, Path]] = []   # (src, rel)
    for src in root_folder_dir.rglob("*"):
        if src.is_file():
            sources.append((src, src.relative_to(root_folder_dir)))

    if not sources:
        return 0

    backup_dir = root_folder_dir.parent / _ROOT_BACKUP_NAME
    log_path   = root_folder_dir.parent / _ROOT_LOG_NAME
    placed: list[str] = []

    # Track which top-level directories we are creating so restore can wipe
    # them entirely — including any game-generated files written into them
    # after deploy (e.g. BepInEx cache/config/log files).
    created_dirs: set[str] = set()

    for src, rel in sources:
        dst = _resolve_root_path(game_root, rel)
        # Record the top-level directory we're about to create (if new).
        # Use the resolved (possibly case-corrected) top-level name.
        top = dst.relative_to(game_root).parts[0] if len(rel.parts) > 1 else None
        if top and not (game_root / top).exists():
            created_dirs.add(top)

        # Back up any pre-existing file so restore can put it back.
        if dst.exists() and not dst.is_symlink():
            bak = backup_dir / rel
            bak.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dst), str(bak))
            _log(f"  Backed up existing {rel} → Root_Backup/")
        elif dst.is_symlink():
            dst.unlink()

        try:
            _transfer(src, dst, mode)
            placed.append(str(rel).replace("\\", "/"))
        except OSError as e:
            _log(f"  WARN: could not transfer root file {rel}: {e}")

    # Write the deployment log: files on the first line block, then a
    # separator, then directories we created that should be fully removed on
    # restore (deepest first so rmtree on each is safe).
    with log_path.open("w", encoding="utf-8") as f:
        f.write("\n".join(placed))
        if created_dirs:
            f.write("\n---dirs---\n")
            f.write("\n".join(sorted(created_dirs)))

    print(f"  [TIMER] deploy_root_folder: transferred {len(placed)} files")
    _log(f"  Root Folder: {len(placed)} file(s) transferred to game root.")
    return len(placed)


def deploy_root_flagged_mods(
    filemap_root_path: Path,
    game_root: Path,
    staging_root: Path,
    mode: LinkMode = LinkMode.HARDLINK,
    strip_prefixes: "set[str] | None" = None,
    per_mod_strip_prefixes: "dict[str, list[str]] | None" = None,
    log_fn=None,
) -> int:
    """Deploy files from root-flagged mods (filemap_root.txt) directly into game_root.

    filemap_root_path      — Profiles/<game>/filemap_root.txt  (written by build_filemap)
    game_root              — the game's install directory (not Data/)
    staging_root           — the mod staging root (same as used by deploy_filemap)
    mode                   — HARDLINK / SYMLINK / COPY
    strip_prefixes         — shared top-level folder names stripped during staging
    per_mod_strip_prefixes — per-mod overrides for strip_prefixes (same as deploy_filemap)

    Files are appended to the same root_folder_deployed.txt log and Root_Backup/ directory
    used by deploy_root_folder(), so restore_root_folder() undoes everything in one pass.

    Returns the number of files transferred.
    """
    _log = _safe_log(log_fn)

    if not filemap_root_path.is_file():
        return 0

    # Read filemap_root.txt — each line is "rel_str\tmod_name"
    entries: list[tuple[str, str]] = []
    with filemap_root_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if "\t" not in line:
                continue
            rel_str, mod_name = line.split("\t", 1)
            entries.append((rel_str, mod_name))

    if not entries:
        return 0

    backup_dir = filemap_root_path.parent / _ROOT_BACKUP_NAME
    log_path   = filemap_root_path.parent / _ROOT_LOG_NAME

    # Read existing log so we can append (deploy_root_folder may run after us)
    existing_placed: list[str] = []
    existing_dirs: list[str] = []
    if log_path.is_file():
        content = log_path.read_text(encoding="utf-8")
        if "---dirs---" in content:
            _files_sec, _dirs_sec = content.split("---dirs---", 1)
            existing_placed = [p for p in _files_sec.splitlines() if p]
            existing_dirs   = [d for d in _dirs_sec.splitlines()  if d]
        else:
            existing_placed = [p for p in content.splitlines() if p]

    existing_placed_set = set(existing_placed)
    placed: list[str] = []
    created_dirs: set[str] = set(existing_dirs)

    # Build a quick dir-resolution cache for game_root lookups
    _dir_cache: dict = {}

    for rel_str, mod_name in entries:
        # Locate source in staging, trying per-mod then shared strip prefixes.
        src = staging_root / mod_name / rel_str
        if not src.is_file():
            _mod_prefixes = (per_mod_strip_prefixes or {}).get(mod_name)
            _candidates = list(_mod_prefixes) if _mod_prefixes else []
            if strip_prefixes:
                _candidates.extend(strip_prefixes)
            for prefix in _candidates:
                candidate = staging_root / mod_name / prefix / rel_str
                if candidate.is_file():
                    src = candidate
                    break
        if not src.is_file():
            _log(f"  WARN: source not found for root-flagged file: {mod_name}/{rel_str}")
            continue

        dst = _resolve_root_path(game_root, Path(rel_str), _dir_cache)
        rel_posix = str(Path(rel_str)).replace("\\", "/")

        # Skip if already placed by a previous call (avoid double-backup)
        if rel_posix in existing_placed_set:
            continue

        # Record whether the top-level dir existed *before* we transferred,
        # so restore knows whether to remove it. Only meaningful for nested paths.
        _top_preexisted = True
        _top_name: str | None = None
        _rel_parts = Path(rel_str).parts
        if len(_rel_parts) > 1:
            try:
                _top_name = dst.relative_to(game_root).parts[0]
            except ValueError:
                _top_name = None
            if _top_name:
                _top_preexisted = (game_root / _top_name).exists()

        # Back up any pre-existing file
        if dst.exists() and not dst.is_symlink():
            bak = backup_dir / Path(rel_str)
            bak.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dst), str(bak))
            _log(f"  Backed up existing {rel_str} → Root_Backup/")
        elif dst.is_symlink():
            dst.unlink()

        try:
            _transfer(src, dst, mode)
            placed.append(rel_posix)
            if _top_name and not _top_preexisted:
                created_dirs.add(_top_name)
        except OSError as e:
            _log(f"  WARN: could not transfer root-flagged file {rel_str}: {e}")

    if not placed:
        return 0

    # Re-write the log, merging with any existing entries from deploy_root_folder
    all_placed = existing_placed + placed
    with log_path.open("w", encoding="utf-8") as f:
        f.write("\n".join(all_placed))
        if created_dirs:
            f.write("\n---dirs---\n")
            f.write("\n".join(sorted(created_dirs)))

    _log(f"  Root-flagged mods: {len(placed)} file(s) transferred to game root.")
    return len(placed)


def restore_root_folder(
    root_folder_dir: Path,
    game_root: Path,
    log_fn=None,
) -> int:
    """Undo a deploy_root_folder() operation.

    Reads the log written by deploy_root_folder(), removes every file that
    was placed into game_root, restores any backed-up originals from
    Root_Backup/, then removes the log and any empty directories left behind.

    root_folder_dir — Profiles/<game>/Root_Folder/  (used to locate the log)
    game_root       — the game's install directory
    Returns the number of files removed from game_root.
    Silently does nothing if the log file is absent (no prior deploy).
    """
    _log = _safe_log(log_fn)
    _t_root_restore = _time.perf_counter()

    log_path   = root_folder_dir.parent / _ROOT_LOG_NAME
    backup_dir = root_folder_dir.parent / _ROOT_BACKUP_NAME

    if not log_path.is_file():
        return 0

    # Parse log: files section and optional ---dirs--- section.
    content = log_path.read_text(encoding="utf-8")
    if "---dirs---" in content:
        files_section, dirs_section = content.split("---dirs---", 1)
    else:
        files_section, dirs_section = content, ""
    placed      = [p for p in files_section.splitlines() if p]
    created_dirs = [d for d in dirs_section.splitlines() if d]
    removed = 0

    # Remove files we placed (parallelised — one lstat + one unlink per worker).
    _game_root_str = str(game_root)
    safe_targets: list[str] = []
    for rel_str in placed:
        dst = game_root / rel_str
        if not _path_under_root(dst, game_root):
            _log(f"  SKIP: path traversal blocked — {rel_str}")
            continue
        safe_targets.append(_game_root_str + "/" + rel_str)

    def _unlink_one(p: str) -> int:
        try:
            st = os.lstat(p)
        except OSError:
            return 0
        if _stat.S_ISLNK(st.st_mode) or _stat.S_ISREG(st.st_mode):
            try:
                os.unlink(p)
                return 1
            except OSError:
                return 0
        return 0

    if safe_targets:
        with concurrent.futures.ThreadPoolExecutor(max_workers=_deploy_workers()) as pool:
            for n in pool.map(_unlink_one, safe_targets):
                removed += n

    # Restore backed-up originals if any.
    if backup_dir.is_dir():
        for bak_src in backup_dir.rglob("*"):
            if not bak_src.is_file():
                continue
            rel = bak_src.relative_to(backup_dir)
            orig = game_root / rel
            if not _path_under_root(orig, game_root):
                _log(f"  SKIP: path traversal blocked — {rel}")
                continue
            orig.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(bak_src), str(orig))
            _log(f"  Restored {rel} from Root_Backup/")
        shutil.rmtree(backup_dir, ignore_errors=True)

    # Remove the log.
    log_path.unlink()

    # Wipe entire top-level directories we freshly created — removes any
    # game-generated files written into them after deploy.
    for dir_name in created_dirs:
        if ".." in dir_name or "/" in dir_name or "\\" in dir_name:
            _log(f"  SKIP: path traversal blocked — {dir_name}/")
            continue
        d = game_root / dir_name
        if not _path_under_root(d, game_root):
            _log(f"  SKIP: path traversal blocked — {dir_name}/")
            continue
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
            _log(f"  Removed created directory {dir_name}/")

    # Remove any empty subdirectories left behind inside pre-existing dirs
    # (e.g. BepInEx/patchers/Tobey/ left empty after our files were removed).
    # Walk deepest-first so parent dirs are checked after their children.
    dirs_to_check: set[Path] = set()
    for rel_str in placed:
        p = (game_root / rel_str).parent
        while p != game_root and p != game_root.parent:
            dirs_to_check.add(p)
            p = p.parent
    for d in sorted(dirs_to_check, key=lambda x: len(x.parts), reverse=True):
        try:
            d.rmdir()  # Only succeeds if the directory is empty
        except OSError:
            pass

    print(f"  [TIMER] restore_root_folder: {_time.perf_counter() - _t_root_restore:.3f}s")
    _log(f"  Root Folder restore: removed {removed} file(s) from game root.")
    return removed


__all__ = [
    "_ROOT_BACKUP_NAME",
    "_ROOT_LOG_NAME",
    "deploy_root_folder",
    "deploy_root_flagged_mods",
    "restore_root_folder",
]
