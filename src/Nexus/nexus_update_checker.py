"""
nexus_update_checker.py
Check installed Nexus mods for available updates.

Workflow:
  1. Scan ``meta.ini`` files in the staging root to find mods with Nexus IDs.
  2. For each mod with a stored ``file_id``, fetch the mod's file list from
     the API and compare against the latest MAIN file.
  3. Return a list of mods that have newer files available.

Usage::

    from Nexus.nexus_update_checker import check_for_updates

    results = check_for_updates(api, staging_root, game_domain="fallout4", progress_cb=print)
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from Nexus.nexus_api import NexusAPI, NexusAPIError, NexusModUpdateInfo
from Nexus.nexus_meta import NexusModMeta, scan_installed_mods, read_meta, write_meta
from Nexus.nexus_requirements import MissingRequirementInfo, check_requirements_from_gql

ProgressCallback = Callable[[str], None]


def _parse_install_date(meta: "NexusModMeta") -> Optional[datetime]:
    """
    Return the installation date for a mod, if determinable.

    Checks in priority order:
    1. ``installed`` field (our ISO format: ``2026-03-05T17:21:25``)
    2. MO2 date-version format: ``version = d2026.1.31.0``

    Returns a timezone-aware UTC datetime, or None if no date is available.
    """
    # 1. Our own installed timestamp
    if meta.installed:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(meta.installed.strip(), fmt)
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue

    # 2. MO2 date-version: "d2026.1.31.0"
    version = (meta.version or "").strip()
    if version.lower().startswith("d"):
        # Strip leading 'd', then take the first 3 numeric parts (Y.M.D)
        parts = version[1:].split(".")
        try:
            year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
            return datetime(year, month, day, tzinfo=timezone.utc)
        except (IndexError, ValueError):
            pass

    return None


def _norm_version(v: str) -> str:
    """Normalise a version string for comparison (strip whitespace and leading v/V)."""
    v = v.strip().lower()
    if v.startswith("v"):
        v = v[1:]
    return v


@dataclass
class UpdateInfo:
    """Information about an available update for a mod."""
    mod_name: str               # local folder name
    mod_id: int
    game_domain: str
    installed_file_id: int
    installed_version: str
    latest_file_id: int
    latest_version: str
    latest_file_name: str = ""
    nexus_url: str = ""


def check_for_updates(
    api: NexusAPI,
    staging_root: Path,
    game_domain: str = "",
    progress_cb: Optional[ProgressCallback] = None,
    save_results: bool = True,
    enabled_only: Optional[set] = None,
    max_workers: int = 10,
) -> tuple[list["UpdateInfo"], list["MissingRequirementInfo"]]:
    """
    Check all Nexus-sourced mods under *staging_root* for updates and missing
    requirements in a single pass.

    A single set of batched GraphQL requests fetches both ``updatedAt``
    (for update detection) and ``modRequirements`` (for dependency checking)
    simultaneously so both checks cost the same as running either one alone —
    and neither consumes the REST hourly rate limit.

    **Update detection:**
    For each mod, ``viewerUpdateAvailable`` is used when non-null (requires the
    user to have tracked/downloaded the mod via Nexus).  Otherwise ``updatedAt``
    is compared against the local install date.

    **Requirements check:**
    Each mod’s listed Nexus requirements are cross-referenced against the set of
    installed mod IDs.  External tools and configured alternatives are filtered
    out via the requirement filter file.

    **REST fallback (threaded):**
    A small number of mods fall back to ``GET /mods/{id}/files`` for an exact
    file-ID + version comparison when GraphQL returns no data for them.  These
    requests consume the hourly rate limit but are expected to be very few.

    Parameters
    ----------
    api : NexusAPI
        Authenticated API client.
    staging_root : Path
        Root of the mod staging area (e.g. ``game.get_mod_staging_path()``).
    game_domain : str
        The Nexus API game domain (e.g. ``"skyrimspecialedition"``).
    progress_cb : callable, optional
        Called with status strings for UI feedback.
    save_results : bool
        If True, write results back to each mod’s ``meta.ini``.
    max_workers : int
        Parallel threads for the REST fallback.  Default is 10.

    Returns
    -------
    tuple[list[UpdateInfo], list[MissingRequirementInfo]]
        ``(updates, missing_requirements)``
    """
    _log = progress_cb or (lambda m: None)

    # 1. Scan installed mods with Nexus metadata
    installed = scan_installed_mods(staging_root)
    if not installed:
        _log("No Nexus-sourced mods found.")
        return [], []

    # Keep a reference to ALL installed mods before applying the enabled_only
    # filter — requirements checking needs the full set to build installed_mod_ids.
    all_installed = installed

    if enabled_only is not None:
        installed = [m for m in installed if m.mod_name in enabled_only]

    # A mod is checkable if it has a file_id (exact comparison) OR a
    # parseable install date (date-based comparison — no file_id needed).
    checkable = [
        m for m in installed
        if m.file_id > 0 or _parse_install_date(m) is not None
    ]
    skipped = len(installed) - len(checkable)

    _log(f"Checking {len(checkable)} Nexus mod(s) for updates"
         f"{f' ({skipped} skipped — no mod ID or install date)' if skipped else ''}...")

    if not checkable:
        _log("No checkable mods found (need a modid plus a fileid or install date).")
        return [], []

    # Determine the domain to use
    if not game_domain:
        game_domain = checkable[0].game_domain.strip().lower()
    if not game_domain:
        _log("No game domain available — cannot check updates.")
        return [], []

    # Deduplicate by mod_id
    by_mod_id: dict[int, list[NexusModMeta]] = {}
    for meta in checkable:
        by_mod_id.setdefault(meta.mod_id, []).append(meta)

    total = len(by_mod_id)
    updates: list[UpdateInfo] = []

    # -----------------------------------------------------------------------
    # 2. Batch GraphQL call — fetch updatedAt + viewerUpdateAvailable for
    #    all mods in a handful of requests instead of one REST call per mod.
    #    This does not consume the REST hourly rate limit.
    # -----------------------------------------------------------------------
    _log("Fetching update info via GraphQL...")
    gql_ids = [(game_domain, mod_id) for mod_id in by_mod_id]
    gql_info: dict[int, NexusModUpdateInfo] = api.graphql_mod_update_info_batch(gql_ids)

    # -----------------------------------------------------------------------
    # 3. Classify each mod: GraphQL date-path, REST fallback, or skip.
    # -----------------------------------------------------------------------
    # Mods that need a REST get_mod_files call (file_id known, no install date)
    rest_fallback: dict[int, list[NexusModMeta]] = {}

    for mod_id, metas in by_mod_id.items():
        info = gql_info.get(mod_id)

        for meta in metas:
            install_date = _parse_install_date(meta)

            # --- Path A: file-level comparison when we know the exact file_id.
            # This is authoritative and must take precedence over date-based
            # checks — a mod installed from a collection gets an install date
            # of "now" even when the collection shipped an older file_id, so
            # the updatedAt-vs-install-date path would miss real updates.
            if meta.file_id > 0:
                rest_fallback.setdefault(mod_id, []).append(meta)
                continue

            # --- Path B: Nexus-native flag (requires user to have tracked the mod)
            if info is not None and info.viewer_update_available is not None:
                has_update = info.viewer_update_available

            # --- Path C: date comparison against GraphQL updatedAt
            elif info is not None and info.updated_at is not None and install_date is not None:
                has_update = info.updated_at > install_date

            # --- Path D: REST fallback via install-date comparison
            elif install_date is not None:
                rest_fallback.setdefault(mod_id, []).append(meta)
                continue  # handled below

            else:
                # No usable comparison data — skip
                continue

            _apply_update_result(
                has_update, meta, mod_id, game_domain,
                latest_version=info.version if info else "",
                latest_file_id=0,
                latest_file_name="",
                updates=updates,
                staging_root=staging_root,
                save_results=save_results,
                _log=_log,
                category_id=info.category_id if info else 0,
                category_name=info.category_name if info else "",
            )

    if not gql_info:
        _log("  GraphQL returned no results — falling back to REST for all mods.")
    else:
        _log(f"  GraphQL check complete. {len(rest_fallback)} mod(s) need file-level check.")

    # -----------------------------------------------------------------------
    # 4. File-level check — use batch files when available, REST only when
    #    GraphQL didn't return the mod (avoids N REST calls for batched mods).
    # -----------------------------------------------------------------------
    if rest_fallback:
        _lock = threading.Lock()

        def _check_with_files(mod_id: int, metas: list[NexusModMeta], files: list) -> None:
            """Process mod(s) using file list — from GraphQL batch or REST."""
            gql_mod_info = gql_info.get(mod_id)
            cat_id = gql_mod_info.category_id if gql_mod_info else 0
            if not files:
                return

            for meta in metas:
                installed_file = (
                    next((f for f in files if f.file_id == meta.file_id), None)
                    if meta.file_id > 0
                    else None
                )
                installed_name = installed_file.name if installed_file else None

                # Find candidates with the exact same display name (all versions of that file)
                if installed_name:
                    name_matches = [f for f in files if f.name == installed_name]
                else:
                    name_matches = []

                if name_matches:
                    latest = max(name_matches, key=lambda f: f.uploaded_timestamp)
                else:
                    # Can't identify the exact file — flag for browser fallback
                    latest = max(files, key=lambda f: f.uploaded_timestamp) if files else None

                if latest is None:
                    continue

                exact_name_match = bool(name_matches)

                install_date = _parse_install_date(meta)
                if meta.file_id > 0:
                    # Exact file-ID comparison — authoritative when we know
                    # which file the user has installed.  Preferred over
                    # date comparison because a freshly-installed collection
                    # mod has install_date == now but may ship an older file.
                    latest_ver = _norm_version(latest.version or latest.mod_version or "")
                    installed_ver = _norm_version(meta.version or "")
                    same_version = latest_ver != "" and latest_ver == installed_ver
                    has_update = latest.file_id != meta.file_id and not same_version
                elif install_date is not None:
                    # Date comparison against the latest file's upload timestamp
                    latest_upload = datetime.fromtimestamp(
                        latest.uploaded_timestamp, tz=timezone.utc
                    )
                    has_update = latest_upload > install_date
                else:
                    continue

                with _lock:
                    _apply_update_result(
                        has_update, meta, mod_id, game_domain,
                        latest_version=latest.version or latest.mod_version or "",
                        latest_file_id=latest.file_id if exact_name_match else 0,
                        latest_file_name=latest.file_name,
                        updates=updates,
                        staging_root=staging_root,
                        save_results=save_results,
                        _log=_log,
                        category_id=cat_id,
                        category_name=gql_mod_info.category_name if gql_mod_info else "",
                    )

        # Use batch files when GraphQL returned them; REST only for mods not in gql_info
        rest_only: dict[int, list[NexusModMeta]] = {}
        for mid, metas in rest_fallback.items():
            info = gql_info.get(mid)
            if info and info.files:
                _check_with_files(mid, metas, info.files)
            else:
                rest_only[mid] = metas

        if rest_only:
            def _check_rest(mod_id: int, metas: list[NexusModMeta]) -> None:
                try:
                    files_resp = api.get_mod_files(game_domain, mod_id)
                    _check_with_files(mod_id, metas, files_resp.files)
                except NexusAPIError as exc:
                    _log(f"  {metas[0].mod_name}: could not fetch files ({exc})")

            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = {
                    pool.submit(_check_rest, mid, metas): mid
                    for mid, metas in rest_only.items()
                }
                for future in as_completed(futures):
                    future.result()

    _log(f"Update check complete: {len(updates)} update(s) available.")

    # -----------------------------------------------------------------------
    # 5. Requirements check — uses the same gql_info batch data, no extra
    #    API calls needed.
    # -----------------------------------------------------------------------
    _log("Checking mod requirements...")
    missing_reqs = check_requirements_from_gql(
        gql_info,
        all_installed,
        game_domain=game_domain,
        staging_root=staging_root,
        progress_cb=_log,
        save_results=save_results,
        enabled_only=enabled_only,
    )

    return updates, missing_reqs


def _apply_update_result(
    has_update: bool,
    meta: NexusModMeta,
    mod_id: int,
    game_domain: str,
    latest_version: str,
    latest_file_id: int,
    latest_file_name: str,
    updates: list,
    staging_root: Path,
    save_results: bool,
    _log: Callable,
    category_id: int = 0,
    category_name: str = "",
) -> None:
    """Record an update (or clear the flag) and persist to meta.ini."""
    if has_update:
        info = UpdateInfo(
            mod_name=meta.mod_name,
            mod_id=mod_id,
            game_domain=game_domain,
            installed_file_id=meta.file_id,
            installed_version=meta.version,
            latest_file_id=latest_file_id,
            latest_version=latest_version,
            latest_file_name=latest_file_name,
            nexus_url=meta.nexus_page_url,
        )
        updates.append(info)
        _log(f"  ↑ {meta.mod_name}: {meta.version or '?'} → {latest_version or '?'}")
        if save_results:
            meta.latest_file_id = latest_file_id
            meta.latest_version = latest_version
            meta.has_update = True
            if category_id > 0:
                meta.category_id = category_id
            if category_name:
                meta.category_name = category_name
            write_meta(staging_root / meta.mod_name / "meta.ini", meta)
    else:
        if save_results:
            changed = False
            if meta.has_update:
                meta.has_update = False
                changed = True
            if latest_file_id and meta.latest_file_id != latest_file_id:
                meta.latest_file_id = latest_file_id
                changed = True
            if latest_version and meta.latest_version != latest_version:
                meta.latest_version = latest_version
                changed = True
            if category_id > 0 and meta.category_id != category_id:
                meta.category_id = category_id
                changed = True
            if category_name and meta.category_name != category_name:
                meta.category_name = category_name
                changed = True
            if changed:
                write_meta(staging_root / meta.mod_name / "meta.ini", meta)
