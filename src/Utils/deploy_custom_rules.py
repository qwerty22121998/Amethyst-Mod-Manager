"""
deploy_custom_rules.py
Custom routing rules (flexible file routing used by Bethesda + others).

Extracted from deploy.py during the 2026-04 refactor. No behaviour changes.
"""

from __future__ import annotations

import concurrent.futures
import fnmatch
import os
import shutil
from pathlib import Path

from Utils.app_log import safe_log as _safe_log
from Utils.deploy_shared import (
    CustomRule,
    LinkMode,
    _deploy_workers,
    _do_link,
    _path_under_root,
    _prune_empty_dirs,
    _resolve_source,
    _restore_backup_dir,
)


_CUSTOM_RULES_LOG_NAME = "custom_rules_deployed.txt"
_CUSTOM_RULES_BACKUP_DIR = "custom_rules_backup"


def _sibling_container(
    rel_str: str, strip_len: int, mod_name: str,
) -> tuple[str, str] | None:
    """Return (container_path, container_name) for an include_siblings primary.

    Include Siblings drags the **topmost folder containing the matched file**:
    every same-mod file under that top-level folder rides along, preserving
    the full rel_path under ``dest``. This way a mod with multiple top-level
    folders (each potentially routed by a different rule) only drags the one
    folder containing the matched file, not the whole mod.

    For "VanillaHUD Plus/lua/vanillahud/utils/x.lua" matching ``utils``,
    the container is "VanillaHUD Plus" — every file under that folder rides
    along to ``dest/VanillaHUD Plus/...``.

    For a file at the mod root (no folder above it), there's nothing to drag
    — returns None.
    """
    del strip_len, mod_name  # unused — container is always the topmost folder
    norm_rel = rel_str.replace("\\", "/")
    if "/" not in norm_rel:
        return None
    container = norm_rel.split("/", 1)[0]
    return (container, container)


def deploy_custom_rules(
    filemap_path: Path,
    game_root: Path,
    staging_root: Path,
    rules: list[CustomRule],
    mode: LinkMode = LinkMode.HARDLINK,
    strip_prefixes: set[str] | None = None,
    per_mod_strip_prefixes: dict[str, list[str]] | None = None,
    log_fn=None,
    progress_fn=None,
) -> set[str]:
    """Deploy filemap entries that match a CustomRule to their designated dirs.

    Matching logic (first matching rule wins): file matches a rule by folder
    (any path segment in rule.folders), extension (rule.extensions), or
    filename (rule.filenames). Placement under ``game_root / rule.dest``
    depends on rule.flatten:
    - flatten=False (default) — preserve the full mod-relative path under dest
    - flatten=True + folder match — strip the prefix above the matched folder,
      keep matched folder + contents under dest
    - flatten=True + ext/filename match — bare filename under dest

    Returns the set of lowercased rel_paths that were handled so the caller
    can exclude them from the normal deploy step.

    A log of placed absolute paths is written to
    filemap_path.parent / "custom_rules_deployed.txt" for use by
    restore_custom_rules().
    """
    if not rules:
        return set()

    _log = _safe_log(log_fn)
    _strip = {p.lower() for p in strip_prefixes} if strip_prefixes else set()
    _per_mod_strip = per_mod_strip_prefixes or {}
    overwrite_dir = staging_root.parent / "overwrite"
    _overwrite_str = str(overwrite_dir)
    _staging_str   = str(staging_root)
    nocase_cache: dict[Path, dict[str, list[Path]]] = {}
    sorted_strip   = sorted(_strip) if _strip else []

    # Pre-process rules into normalised form for fast matching.
    # Extensions are kept as a list sorted longest-first so that multi-dot
    # extensions like ".dekcns.json" win over their plain ".json" suffix.
    _rules: list[tuple[CustomRule, set[str], list[str], set[str]]] = []
    for rule in rules:
        ext_list = sorted({e.lower() for e in rule.extensions}, key=len, reverse=True)
        _rules.append((
            rule,
            {f.lower() for f in rule.folders},
            ext_list,
            {n.lower() for n in rule.filenames},
        ))

    def _ext_match(filename: str, exts: list[str]) -> str | None:
        """Return the longest extension in ``exts`` that ``filename`` ends with
        (as ``.something``), or None. ``exts`` must be sorted longest-first.
        """
        for e in exts:
            if filename.endswith(e) and len(filename) > len(e):
                return e
        return None

    def _name_match(filename: str, names: set[str]) -> bool:
        """Match ``filename`` (lowercased) against the rule's filenames.
        Glob characters (``*``, ``?``, ``[seq]``) are honoured so a rule can
        target e.g. ``*.dekcns.json``; plain entries match by exact equality.
        """
        for n in names:
            if any(c in n for c in "*?["):
                if fnmatch.fnmatchcase(filename, n):
                    return True
            elif filename == n:
                return True
        return False

    def _match_single_rule(
        rel_lower: str,
        rule: CustomRule, folders: set[str], exts: list[str], filenames: set[str],
    ) -> tuple[int, str] | None:
        """Check whether ``rel_lower`` matches a *single* rule.

        Returns ``(strip_len, matched_ext)`` on a match, or None. Same
        semantics as the old multi-rule ``_match_rule`` but for one rule —
        used by the rule-ordered first pass so include_siblings drags from
        an earlier rule can pre-empt primary matches for later rules.
        """
        parts = rel_lower.split("/")
        filename = parts[-1]
        is_loose = len(parts) == 1
        strip_len = -1
        folder_hit = False
        if folders:
            for f in folders:
                if "/" in f:
                    idx = rel_lower.find(f + "/")
                    if idx < 0 and rel_lower.endswith(f):
                        idx = len(rel_lower) - len(f)
                    if idx >= 0 and (idx == 0 or rel_lower[idx - 1] == "/"):
                        strip_len = idx
                        folder_hit = True
                        break
                else:
                    for pi, seg in enumerate(parts[:-1]):
                        if seg == f:
                            strip_len = sum(len(parts[j]) + 1 for j in range(pi))
                            folder_hit = True
                            break
                    if folder_hit:
                        break
            if folder_hit and rule.loose_only and strip_len != 0:
                return None
        matched_ext = _ext_match(filename, exts) if exts else None
        if folder_hit and (not exts or matched_ext is not None):
            return strip_len, matched_ext or ""
        if rule.loose_only and not is_loose:
            return None
        if matched_ext is not None and not folders and not filenames:
            return -1, matched_ext
        if filenames and _name_match(filename, filenames):
            return -1, ""
        return None

    def _match_rule(rel_lower: str) -> tuple[CustomRule, int, str] | None:
        """First-match-wins multi-rule lookup. Kept for backwards-compat;
        the main flow uses ``_match_single_rule`` rule-by-rule so earlier
        rules' include_siblings drags can claim files before later rules
        get to run their primary match.
        """
        for rule, folders, exts, filenames in _rules:
            hit = _match_single_rule(rel_lower, rule, folders, exts, filenames)
            if hit is not None:
                strip_len, matched_ext = hit
                return rule, strip_len, matched_ext
        return None

    tasks: list[tuple[Path, Path]] = []   # (src, dst)
    handled_lower: set[str] = set()
    # primary_matches: rel_lower -> (rule, strip_len, rel_str, mod_name, matched_ext)
    primary_matches: dict[str, tuple[CustomRule, int, str, str, str]] = {}
    # entries_by_parent: parent_lower -> list of (rel_str, mod_name, name_lower)
    entries_by_parent: dict[str, list[tuple[str, str, str]]] = {}
    # all_entries: full list of (rel_str, mod_name, rel_lower)
    all_entries: list[tuple[str, str, str]] = []
    # Pre-load every entry once so the per-rule loop below can iterate them
    # repeatedly (skipping any already claimed by an earlier rule).
    seen_lower: set[str] = set()
    with filemap_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if "\t" not in line:
                continue
            rel_str, mod_name = line.split("\t", 1)
            rel_lower = rel_str.lower()
            if rel_lower in seen_lower:
                continue
            seen_lower.add(rel_lower)
            parent_lower, _, name_lower = rel_lower.rpartition("/")
            entries_by_parent.setdefault(parent_lower, []).append(
                (rel_str, mod_name, name_lower)
            )
            all_entries.append((rel_str, mod_name, rel_lower))

    def _place_primary(rel_str: str, mod_name: str, rule: CustomRule,
                       strip_len: int, matched_ext: str) -> None:
        """Resolve source, compute destination, and append a copy task for a
        rule's primary match. Updates primary_matches/handled_lower/tasks.
        """
        rel_lower = rel_str.lower()
        primary_matches[rel_lower] = (rule, strip_len, rel_str, mod_name, matched_ext)
        src_str = _resolve_source(
            mod_name, rel_str, rel_lower, overwrite_dir, staging_root,
            _overwrite_str, _staging_str, sorted_strip, _per_mod_strip,
            nocase_cache,
        )
        if src_str is None:
            _log(f"  WARN: source not found — {rel_str} ({mod_name})")
            handled_lower.add(rel_lower)  # claim it anyway so later rules don't re-try
            return
        src = Path(src_str)
        dest_base = game_root / rule.dest if rule.dest else game_root
        container_info = _sibling_container(rel_str, strip_len, mod_name) \
            if rule.include_siblings else None
        if container_info is not None:
            norm_rel = rel_str.replace("\\", "/")
            container_path, container_name = container_info
            if container_path:
                rel_in_container = norm_rel[len(container_path) + 1:]
            else:
                rel_in_container = norm_rel
            dst = dest_base / container_name / rel_in_container
        elif rule.flatten:
            if strip_len >= 0:
                kept = rel_str[strip_len:].lstrip("/")
                dst = dest_base / kept if kept else dest_base
            else:
                dst = dest_base / src.name
        else:
            dst = dest_base / rel_str
        tasks.append((src, dst))
        handled_lower.add(rel_lower)

    def _drag_container(container_lower: str, container_name: str,
                        primary_mod: str, rule: CustomRule, is_whole_mod: bool) -> None:
        """Drag every unclaimed same-mod file under ``container_lower`` to
        ``dest/container_name/<rel-from-container>``.
        """
        prefix_lower = container_lower + "/" if container_lower else ""
        dest_base = game_root / rule.dest if rule.dest else game_root
        for sib_rel_str, sib_mod_name, sib_lower in all_entries:
            if sib_lower in handled_lower:
                continue
            if sib_mod_name != primary_mod:
                continue
            if is_whole_mod:
                rel_in_container = sib_rel_str.replace("\\", "/")
            else:
                if not sib_lower.startswith(prefix_lower):
                    continue
                rel_in_container = sib_rel_str.replace("\\", "/")[len(container_lower) + 1:]
            src_str = _resolve_source(
                sib_mod_name, sib_rel_str, sib_lower, overwrite_dir, staging_root,
                _overwrite_str, _staging_str, sorted_strip, _per_mod_strip,
                nocase_cache,
            )
            if src_str is None:
                _log(f"  WARN: source not found — {sib_rel_str} ({sib_mod_name})")
                handled_lower.add(sib_lower)
                continue
            src = Path(src_str)
            dst = dest_base / container_name / rel_in_container
            tasks.append((src, dst))
            handled_lower.add(sib_lower)

    # Process rules in declaration order. For each rule:
    #   1. Find every still-unclaimed file that matches this rule and place
    #      it as a primary.
    #   2. If include_siblings is on, immediately drag the container of
    #      every just-placed primary so later rules can't claim those files.
    # This ordering is what enforces "rule order wins" — if rule 1's drag
    # would swallow a file that rule 2 would also match, rule 1 takes it.
    for rule, folders, exts, filenames in _rules:
        # Step 1: claim primaries for this rule among unclaimed files.
        new_primaries: list[tuple[str, str, int, str]] = []
        for rel_str, mod_name, rel_lower in all_entries:
            if rel_lower in handled_lower:
                continue
            hit = _match_single_rule(rel_lower, rule, folders, exts, filenames)
            if hit is None:
                continue
            strip_len, matched_ext = hit
            _place_primary(rel_str, mod_name, rule, strip_len, matched_ext)
            new_primaries.append((rel_str, mod_name, strip_len, matched_ext))
        # Step 2: drag siblings for include_siblings primaries (per-mod).
        # Whole-mod drags subsume nested ones, so process them first.
        if not rule.include_siblings or not new_primaries:
            continue
        drags: list[tuple[str, str, str, bool]] = []  # (cont_lower, cont_name, mod_name, whole)
        for rel_str, mod_name, strip_len, _matched_ext in new_primaries:
            info = _sibling_container(rel_str, strip_len, mod_name)
            if info is None:
                continue
            container_path, container_name = info
            drags.append((container_path.lower(), container_name, mod_name,
                          container_path == ""))
        # Whole-mod first, then longest container first.
        drags.sort(key=lambda t: (0 if t[3] else 1, -len(t[0])))
        seen_drags: set[tuple[str, str]] = set()  # (container_lower, mod_name)
        for cont_lower, cont_name, mod_name, is_whole_mod in drags:
            key = (cont_lower, mod_name)
            if key in seen_drags:
                continue
            seen_drags.add(key)
            _drag_container(cont_lower, cont_name, mod_name, rule, is_whole_mod)

    # Second pass: companion files ride along with their primary match.
    # Companions are matched longest-first too so a ".dekcns.json" companion
    # would beat a ".json" one.
    for rel_lower, (rule, strip_len, rel_str, _mod_name, matched_ext) in list(primary_matches.items()):
        companions = sorted(
            {c.lower() for c in rule.companion_extensions}, key=len, reverse=True
        )
        if not companions:
            continue
        parent_lower, _, name_lower = rel_lower.rpartition("/")
        # Stem is the primary filename minus the extension that matched.
        # Falls back to splitext when there was no extension match (folder/
        # filename rules) — companions remain stem-relative in that case.
        if matched_ext and name_lower.endswith(matched_ext):
            stem_lower = name_lower[: -len(matched_ext)]
        else:
            stem_lower, _ = os.path.splitext(name_lower)
        siblings = entries_by_parent.get(parent_lower, ())
        stem_dot = stem_lower + "."
        for sib_rel_str, sib_mod_name, sib_name_lower in siblings:
            sib_lower = sib_rel_str.lower()
            if sib_lower in handled_lower:
                continue
            if not sib_name_lower.startswith(stem_dot):
                continue
            sib_ext = None
            for c in companions:
                if sib_name_lower.endswith(c) and len(sib_name_lower) > len(c):
                    sib_ext = c
                    break
            if sib_ext is None:
                continue
            src_str = _resolve_source(
                sib_mod_name, sib_rel_str, sib_lower, overwrite_dir, staging_root,
                _overwrite_str, _staging_str, sorted_strip, _per_mod_strip,
                nocase_cache,
            )
            if src_str is None:
                _log(f"  WARN: source not found — {sib_rel_str} ({sib_mod_name})")
                continue
            src = Path(src_str)
            dest_base = game_root / rule.dest if rule.dest else game_root
            if rule.flatten:
                if strip_len >= 0:
                    kept = sib_rel_str[strip_len:].lstrip("/")
                    dst = dest_base / kept if kept else dest_base
                else:
                    dst = dest_base / src.name
            else:
                dst = dest_base / sib_rel_str
            tasks.append((src, dst))
            handled_lower.add(sib_lower)

    if not tasks:
        return handled_lower

    # Backup directory for vanilla files that will be overwritten
    backup_dir = filemap_path.parent / _CUSTOM_RULES_BACKUP_DIR
    if backup_dir.exists():
        shutil.rmtree(backup_dir)

    # Create destination directories
    needed_dirs: set[Path] = {dst.parent for _, dst in tasks}
    for d in needed_dirs:
        d.mkdir(parents=True, exist_ok=True)

    placed_abs: list[str] = []
    total = len(tasks)
    _game_root = game_root

    # Back up any vanilla files we are about to overwrite (must be serial).
    for src, dst in tasks:
        if dst.exists() and not dst.is_symlink():
            try:
                rel = dst.relative_to(_game_root)
                bak = backup_dir / rel
                bak.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(dst), str(bak))
            except (ValueError, OSError) as e:
                _log(f"  WARN: could not back up {dst}: {e}")
        elif dst.is_symlink():
            dst.unlink()

    # Transfer files in parallel.
    transfer_tasks: list[tuple[str, str]] = [(str(s), str(d)) for s, d in tasks]

    def _do_custom(item: tuple[str, str]) -> tuple[str | None, tuple[str, OSError] | None]:
        src_s, dst_s = item
        err = _do_link(src_s, dst_s, mode)
        if err is None:
            return dst_s, None
        return None, (dst_s, err)

    done_count = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=_deploy_workers()) as pool:
        for result, err in pool.map(_do_custom, transfer_tasks):
            done_count += 1
            if result is not None:
                placed_abs.append(result)
            elif err is not None:
                dst_err, exc = err
                _log(f"  WARN: could not transfer {dst_err}: {exc}")
            if progress_fn is not None and (done_count % 200 == 0 or done_count == total):
                progress_fn(done_count, total)

    log_path = filemap_path.parent / _CUSTOM_RULES_LOG_NAME
    try:
        if placed_abs:
            log_path.write_text("\n".join(placed_abs), encoding="utf-8")
        elif log_path.exists():
            log_path.unlink()
    except OSError:
        pass

    _log(f"  Custom rules: placed {len(placed_abs)} file(s).")
    return handled_lower


def restore_custom_rules(
    filemap_path: Path,
    game_root: Path,
    rules: list[CustomRule],
    log_fn=None,
) -> int:
    """Remove files placed by deploy_custom_rules() and prune empty dest dirs.

    Reads filemap_path.parent / "custom_rules_deployed.txt", deletes every
    listed absolute path, then tries to rmdir each rule's destination directory
    (silently ignored if non-empty).  Returns the number of files removed.
    """
    _log = _safe_log(log_fn)
    log_path = filemap_path.parent / _CUSTOM_RULES_LOG_NAME
    backup_dir = filemap_path.parent / _CUSTOM_RULES_BACKUP_DIR

    if not log_path.is_file():
        return 0

    placed = [p for p in log_path.read_text(encoding="utf-8").splitlines() if p]
    removed = 0
    dirs_to_prune: set[Path] = set()
    _game_root_resolved = game_root.resolve()
    for abs_str in placed:
        p = Path(abs_str)
        # Use the unresolved path for the under-root check so symlinks
        # (whose targets live outside game_root) are not incorrectly blocked.
        try:
            p.relative_to(game_root)
        except ValueError:
            try:
                p.resolve().relative_to(_game_root_resolved)
            except ValueError:
                _log(f"  SKIP: path traversal blocked — {abs_str}")
                continue
        if p.is_file() or p.is_symlink():
            p.unlink()
            removed += 1
        # Collect parent dirs for pruning (stop at game_root, unresolved check)
        parent = p.parent
        while parent != game_root:
            try:
                parent.relative_to(game_root)
            except ValueError:
                break
            dirs_to_prune.add(parent)
            parent = parent.parent

    # Restore backed-up vanilla files
    _restore_backup_dir(backup_dir, game_root, _log)

    # Prune empty subdirectories deepest-first; never touch game_root itself
    _prune_empty_dirs(dirs_to_prune, stop_dirs={game_root})

    log_path.unlink()
    _log(f"  Custom rules restore: removed {removed} file(s).")
    return removed


__all__ = [
    "_CUSTOM_RULES_LOG_NAME",
    "_CUSTOM_RULES_BACKUP_DIR",
    "deploy_custom_rules",
    "restore_custom_rules",
]
