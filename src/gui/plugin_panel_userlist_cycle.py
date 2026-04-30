"""
Userlist editing and cycle-detection mixin for PluginPanel.

Owns:
- The plugin cycle overlay (open/close/refresh) that visualises userlist rule
  cycles and lets the user flip a plugin rule from "after"↔"before" to break a
  cycle.
- userlist.yaml I/O — `_parse_userlist`, `_write_userlist`, `_get_userlist_path`.
- Tarjan's-SCC cycle analyzer (`_analyze_userlist_cycles`) and the convenience
  helper `_userlist_rule_component` for finding all plugins reachable through
  userlist rules from a given plugin.
- Inline panels: the userlist edit panel (`_ul_save` / `_ul_cancel` /
  `_add_plugin_to_userlist`) and the group assignment panel (`_grp_save` /
  `_grp_cancel` / `_add_plugins_to_group`).
- Add/remove plugin entries from userlist.yaml.

Host (PluginPanel) owns:
- State: `_plugin_entries`, `_userlist_plugins`, `_plugin_group_map`,
  `_userlist_cycle_plugins`, `_userlist_cycle_components`,
  `_userlist_cycle_edges`, `_plugin_cycle_overlay`, `_plugin_cycle_anchor`,
  `_plugin_cycle_scope`. All initialised in `__init__`.
- Inline-panel widgets built in toolbar setup: `_ul_panel`, `_ul_after_var`,
  `_ul_before_var`, `_ul_name_label`, `_userlist_panel_plugin`,
  `_userlist_panel_idx`; `_grp_panel`, `_grp_menu`, `_grp_var`,
  `_grp_name_label`, `_group_panel_plugins`.
- Hooks: `_log`, `_predraw`.
"""

import re
from pathlib import Path

from Utils.atomic_write import write_atomic_text
from gui.game_helpers import _GAMES
from gui.plugin_cycle_overlay import PluginCycleOverlay


class PluginPanelUserlistCycleMixin:
    """userlist.yaml editing, cycle analysis, and the cycle overlay."""

    # ------------------------------------------------------------------
    # Cycle overlay — open / refresh / close + flip
    # ------------------------------------------------------------------

    def _open_plugin_cycle_overlay(self, plugin_name: str):
        """Show the cycle / userlist-rule overlay for plugin_name.

        If plugin_name is in an SCC, the scope is that SCC (cycle view). If
        it's just a userlist-managed plugin, the scope is the set of plugins
        reachable via any userlist rule (weakly-connected component) so the
        user can visualise all rules touching this plugin.
        """
        self._close_plugin_cycle_overlay()
        name_lower = plugin_name.lower()
        component = self._userlist_cycle_components.get(name_lower)
        if not component:
            component = self._userlist_rule_component(name_lower)
        if not component:
            self._log(f"{plugin_name} has no userlist rules to display.")
            return
        mod_panel = getattr(self.winfo_toplevel(), "_mod_panel", None)
        if mod_panel is None:
            self._log("Cannot find modlist panel.")
            return

        self._plugin_cycle_anchor = name_lower
        # Freeze the plugin set at open time. Subsequent flips keep showing
        # these plugins' rules even if the cycle is gone, so the user can
        # revert or adjust further.
        self._plugin_cycle_scope = component
        panel = PluginCycleOverlay(
            mod_panel,
            starting_plugin=plugin_name,
            on_close=self._close_plugin_cycle_overlay,
            on_flip=self._flip_plugin_rule,
        )
        panel.place(relx=0, rely=0, relwidth=1, relheight=1)
        panel.lift()
        self._plugin_cycle_overlay = panel
        self._refresh_cycle_overlay_data()

    def _userlist_rule_component(self, name_lower: str) -> frozenset[str]:
        """Return every plugin reachable from name_lower through userlist
        rules (treated as undirected). Plugin before/after rules and
        group-rule expansions both count. Includes the starting plugin
        itself even if it has no rules yet.
        """
        ul_path = self._get_userlist_path()
        if ul_path is None or not ul_path.is_file():
            return frozenset()
        data = self._parse_userlist(ul_path)

        neigh: dict[str, set[str]] = {}
        def _link(a: str, b: str):
            if not a or not b or a == b:
                return
            neigh.setdefault(a, set()).add(b)
            neigh.setdefault(b, set()).add(a)

        for entry in data.get("plugins", []):
            nm = (entry.get("name") or "").lower()
            if not nm:
                continue
            neigh.setdefault(nm, set())
            for o in entry.get("after", []) or []:
                _link(nm, o.lower())
            for o in entry.get("before", []) or []:
                _link(nm, o.lower())

        group_members: dict[str, list[str]] = {}
        for entry in data.get("plugins", []):
            nm = (entry.get("name") or "").lower()
            grp = entry.get("group")
            if nm and grp:
                group_members.setdefault(grp, []).append(nm)
        for entry in data.get("groups", []):
            g = entry.get("name")
            if not g:
                continue
            dests = group_members.get(g, [])
            for ag in entry.get("after", []) or []:
                sources = group_members.get(ag, [])
                for u in sources:
                    for v in dests:
                        _link(u, v)

        if name_lower not in neigh:
            # Plugin is in userlist but with no rules at all — show just it.
            return frozenset({name_lower})

        seen: set[str] = set()
        stack = [name_lower]
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            stack.extend(neigh.get(n, ()))
        return frozenset(seen)

    def _refresh_cycle_overlay_data(self):
        """Push current scope plugins + all their plugin rules to the overlay."""
        panel = getattr(self, "_plugin_cycle_overlay", None)
        anchor = getattr(self, "_plugin_cycle_anchor", "")
        scope = getattr(self, "_plugin_cycle_scope", frozenset())
        if panel is None or not anchor or not scope:
            return

        display: dict[str, str] = {}
        for entry in self._plugin_entries:
            display[entry.name.lower()] = entry.name
        ul_path = self._get_userlist_path()
        data = self._parse_userlist(ul_path) if (ul_path and ul_path.is_file()) else {"plugins": [], "groups": []}
        for entry in data.get("plugins", []):
            raw = entry.get("name") or ""
            if raw:
                display.setdefault(raw.lower(), raw)

        # Re-run analyzer on the fresh YAML to get cycle membership for the
        # banner + per-edge cyclic flag. This is separate from the global
        # analyze that's already stored on the panel because we want rules
        # even from non-cyclic edges now.
        info = self._analyze_userlist_cycles(data)
        cycle_plugins = info["plugins"]
        cycle_components = info["components"]

        # All plugin rules between scope plugins (cyclic or not).
        scope_edges: dict[tuple[str, str], list[dict]] = {}
        for entry in data.get("plugins", []):
            raw = entry.get("name") or ""
            name = raw.lower()
            if name not in scope:
                continue
            for other in entry.get("after", []) or []:
                ol = other.lower()
                if ol not in scope:
                    continue
                scope_edges.setdefault((ol, name), []).append({
                    "kind": "plugin",
                    "text": f"plugin rule: {raw} 'after' {other}",
                    "owner": raw,
                    "field": "after",
                    "target": other,
                    "id": (name, "after", ol),
                })
            for other in entry.get("before", []) or []:
                ol = other.lower()
                if ol not in scope:
                    continue
                scope_edges.setdefault((name, ol), []).append({
                    "kind": "plugin",
                    "text": f"plugin rule: {raw} 'before' {other}",
                    "owner": raw,
                    "field": "before",
                    "target": other,
                    "id": (name, "before", ol),
                })
        # Group rules — informational only. Any group→group rule where both
        # ends include at least one scope plugin shows up here.
        group_members: dict[str, list[str]] = {}
        for entry in data.get("plugins", []):
            name = (entry.get("name") or "").lower()
            grp = entry.get("group")
            if name and grp:
                group_members.setdefault(grp, []).append(name)
        for entry in data.get("groups", []):
            g_name = entry.get("name")
            if not g_name:
                continue
            dests = group_members.get(g_name, [])
            for after_group in entry.get("after", []) or []:
                sources = group_members.get(after_group, [])
                for u in sources:
                    for v in dests:
                        if u in scope and v in scope:
                            scope_edges.setdefault((u, v), []).append({
                                "kind": "group",
                                "text": (
                                    f"group rule: '{g_name}' after '{after_group}' "
                                    f"({display.get(u, u)} in '{after_group}' → "
                                    f"{display.get(v, v)} in '{g_name}')"
                                ),
                            })

        # Mark which edges still form part of a cycle so the overlay can
        # annotate them. Edge (u, v) is cyclic iff u and v share an SCC AND
        # that SCC has size ≥ 2 (or a self-loop — guaranteed by analyzer).
        cyclic_edges: set[tuple[str, str]] = set()
        for (u, v) in scope_edges:
            cu = cycle_components.get(u)
            cv = cycle_components.get(v)
            if cu is not None and cu is cv:
                cyclic_edges.add((u, v))

        is_broken = any(p in cycle_plugins for p in scope)

        # Compute which plugin rules, if flipped in isolation, would leave no
        # cycle inside the scope. These get highlighted as single-flip fixes.
        fixable_reasons: set[tuple[str, str, str]] = set()
        if is_broken:
            # Collect unique plugin rules from cyclic edges — flipping a
            # non-cyclic rule can't break a cycle that doesn't touch it.
            seen: set[tuple[str, str, str]] = set()
            for edge in cyclic_edges:
                for reason in scope_edges.get(edge, []):
                    if reason.get("kind") != "plugin":
                        continue
                    rid = reason.get("id")
                    if rid is None or rid in seen:
                        continue
                    seen.add(rid)
                    if self._would_flip_resolve(data, reason, scope):
                        fixable_reasons.add(rid)

        panel.update_cycle(
            starting_plugin=display.get(anchor, anchor),
            scope_plugins=scope,
            scope_edges=scope_edges,
            cyclic_edges=cyclic_edges,
            fixable_reasons=fixable_reasons,
            display_names=display,
            is_broken=is_broken,
        )

    def _would_flip_resolve(self, data: dict, reason: dict, scope: frozenset[str]) -> bool:
        """Return True iff flipping this plugin rule (in isolation) leaves no
        cycle inside `scope`. Uses an in-memory copy of the userlist data."""
        owner = reason.get("owner", "")
        target = reason.get("target", "")
        field = reason.get("field", "")
        if field not in ("after", "before") or not owner or not target:
            return False
        owner_l = owner.lower()
        target_l = target.lower()
        other = "before" if field == "after" else "after"

        # Shallow copy the plugins list; deep copy only the owner entry we mutate.
        sim_plugins = []
        for entry in data.get("plugins", []):
            if (entry.get("name") or "").lower() == owner_l:
                e2 = dict(entry)
                e2[field] = [t for t in (entry.get(field, []) or []) if t.lower() != target_l]
                if not e2[field]:
                    e2.pop(field, None)
                opp = list(entry.get(other, []) or [])
                if not any(t.lower() == target_l for t in opp):
                    opp.append(target)
                e2[other] = opp
                sim_plugins.append(e2)
            else:
                sim_plugins.append(entry)
        sim_data = {"plugins": sim_plugins, "groups": data.get("groups", [])}
        sim_info = self._analyze_userlist_cycles(sim_data)
        return not any(p in sim_info["plugins"] for p in scope)

    def _flip_plugin_rule(self, owner: str, field: str, target: str) -> None:
        """Move `target` from the given field of `owner`'s userlist entry to
        the opposite field. Triggered by the cycle overlay's flip buttons."""
        if field not in ("after", "before"):
            return
        ul_path = self._get_userlist_path()
        if ul_path is None or not ul_path.is_file():
            self._log("userlist.yaml not found — cannot flip rule.")
            return

        data = self._parse_userlist(ul_path)
        owner_lower = owner.lower()
        target_lower = target.lower()
        other = "before" if field == "after" else "after"

        changed = False
        for entry in data.get("plugins", []):
            if (entry.get("name") or "").lower() != owner_lower:
                continue
            cur = entry.get(field, []) or []
            new_cur = [t for t in cur if t.lower() != target_lower]
            if len(new_cur) == len(cur):
                continue  # target not actually present — nothing to flip
            if new_cur:
                entry[field] = new_cur
            else:
                entry.pop(field, None)
            opposite = entry.get(other, []) or []
            if not any(t.lower() == target_lower for t in opposite):
                opposite.append(target)
                entry[other] = opposite
            changed = True
            break

        if not changed:
            self._log(f"Rule {owner} '{field}' {target} not found in userlist.yaml.")
            return

        self._write_userlist(ul_path, data)
        self._log(f"Flipped: {owner} now '{other}' {target}")
        self._refresh_userlist_set()
        self._predraw()
        self._refresh_cycle_overlay_data()

    def _close_plugin_cycle_overlay(self):
        panel = getattr(self, "_plugin_cycle_overlay", None)
        if panel:
            try:
                panel.destroy()
            except Exception:
                pass
        self._plugin_cycle_overlay = None
        self._plugin_cycle_anchor = ""
        self._plugin_cycle_scope = frozenset()

    # ------------------------------------------------------------------
    # Userlist helpers
    # ------------------------------------------------------------------

    def _refresh_userlist_set(self) -> None:
        """Reload the set of plugin names present in userlist.yaml."""
        ul_path = self._get_userlist_path()
        if ul_path and ul_path.is_file():
            data = self._parse_userlist(ul_path)
            self._userlist_plugins = {
                e["name"].lower() for e in data["plugins"] if e.get("name")
            }
            self._plugin_group_map = {
                e["name"].lower(): e["group"]
                for e in data["plugins"]
                if e.get("name") and e.get("group") and e["group"] != "default"
            }
            info = self._analyze_userlist_cycles(data)
            self._userlist_cycle_plugins = info["plugins"]
            self._userlist_cycle_components = info["components"]
            self._userlist_cycle_edges = info["edges"]
        else:
            self._userlist_plugins = set()
            self._plugin_group_map = {}
            self._userlist_cycle_plugins = set()
            self._userlist_cycle_components = {}
            self._userlist_cycle_edges = {}

    @staticmethod
    def _analyze_userlist_cycles(data: dict) -> dict:
        """Analyze userlist.yaml and return cycle information.

        Builds a directed graph from userlist plugin before/after rules and
        group after rules (every plugin in group G inherits "after X" for each
        X listed on G's after entry, meaning every plugin in group X must load
        before every plugin in G). Runs Tarjan's SCC; any node inside a
        non-trivial strongly-connected component (size ≥ 2, or with a self
        edge) participates in a cycle.

        Returns a dict:
          {
            "plugins":    set[str] — every plugin in any cycle (lowercased),
            "components": dict[str, frozenset[str]] — plugin → SCC membership,
            "edges":      dict[(u, v), list[dict]] — structured reasons.
          }
        Each edge reason is a dict like:
          {"kind": "plugin", "text": str,
           "owner": raw_name, "field": "after"|"before", "target": raw_name}
          {"kind": "group", "text": str}
        'kind=plugin' entries can be flipped by the overlay (move target between
        the owner entry's after/before lists). Group reasons are informational.
        """
        plugins = data.get("plugins", []) or []
        groups = data.get("groups", []) or []

        empty = {"plugins": set(), "components": {}, "edges": {}}
        if not plugins and not groups:
            return empty

        # Edge u → v means "u must load before v". Reasons list per edge so
        # the overlay can explain each cycle edge.
        adj: dict[str, set[str]] = {}
        edges: dict[tuple[str, str], list[dict]] = {}
        display: dict[str, str] = {}

        def _add_edge(u: str, v: str, reason: dict) -> None:
            if not u or not v:
                return
            adj.setdefault(u, set()).add(v)
            adj.setdefault(v, set())
            edges.setdefault((u, v), []).append(reason)

        # Plugin-level rules. Track display casing from the entries.
        for entry in plugins:
            raw = entry.get("name") or ""
            name = raw.lower()
            if not name:
                continue
            display.setdefault(name, raw)
            adj.setdefault(name, set())
            for other in entry.get("after", []) or []:
                other_l = other.lower()
                display.setdefault(other_l, other)
                _add_edge(other_l, name, {
                    "kind": "plugin",
                    "text": f"plugin rule: {raw} 'after' {other}",
                    "owner": raw,
                    "field": "after",
                    "target": other,
                })
            for other in entry.get("before", []) or []:
                other_l = other.lower()
                display.setdefault(other_l, other)
                _add_edge(name, other_l, {
                    "kind": "plugin",
                    "text": f"plugin rule: {raw} 'before' {other}",
                    "owner": raw,
                    "field": "before",
                    "target": other,
                })

        # Group-level rules — expand each group-after into plugin-plugin edges.
        group_members: dict[str, list[str]] = {}
        for entry in plugins:
            name = (entry.get("name") or "").lower()
            grp = entry.get("group")
            if name and grp:
                group_members.setdefault(grp, []).append(name)
        for entry in groups:
            g_name = entry.get("name")
            if not g_name:
                continue
            dests = group_members.get(g_name, [])
            if not dests:
                continue
            for after_group in entry.get("after", []) or []:
                sources = group_members.get(after_group, [])
                for u in sources:
                    for v in dests:
                        _add_edge(u, v, {
                            "kind": "group",
                            "text": (
                                f"group rule: '{g_name}' after '{after_group}' "
                                f"({display.get(u, u)} in '{after_group}' → "
                                f"{display.get(v, v)} in '{g_name}')"
                            ),
                        })

        if not adj:
            return empty

        # Tarjan's SCC, iterative.
        index = 0
        indices: dict[str, int] = {}
        low: dict[str, int] = {}
        on_stack: set[str] = set()
        stack: list[str] = []
        cycle_plugins: set[str] = set()
        components: dict[str, frozenset[str]] = {}

        for start in list(adj.keys()):
            if start in indices:
                continue
            work: list[tuple[str, iter]] = [(start, iter(adj[start]))]
            indices[start] = low[start] = index
            index += 1
            stack.append(start)
            on_stack.add(start)
            while work:
                node, it = work[-1]
                nxt = next(it, None)
                if nxt is None:
                    if low[node] == indices[node]:
                        component: list[str] = []
                        while True:
                            w = stack.pop()
                            on_stack.discard(w)
                            component.append(w)
                            if w == node:
                                break
                        if len(component) > 1 or node in adj.get(node, ()):
                            frozen = frozenset(component)
                            cycle_plugins.update(component)
                            for w in component:
                                components[w] = frozen
                    work.pop()
                    if work:
                        parent = work[-1][0]
                        if low[node] < low[parent]:
                            low[parent] = low[node]
                    continue
                if nxt not in indices:
                    indices[nxt] = low[nxt] = index
                    index += 1
                    stack.append(nxt)
                    on_stack.add(nxt)
                    work.append((nxt, iter(adj[nxt])))
                elif nxt in on_stack:
                    if indices[nxt] < low[node]:
                        low[node] = indices[nxt]

        # Only keep edges that are fully inside a cycle — irrelevant edges
        # would clutter the overlay.
        cycle_edges: dict[tuple[str, str], list[dict]] = {}
        for (u, v), reasons in edges.items():
            if u in cycle_plugins and v in cycle_plugins and components.get(u) is components.get(v):
                cycle_edges[(u, v)] = reasons

        return {
            "plugins": cycle_plugins,
            "components": components,
            "edges": cycle_edges,
        }

    def _get_userlist_path(self) -> Path | None:
        game = _GAMES.get(self.winfo_toplevel()._topbar._game_var.get())
        active_dir = getattr(game, "_active_profile_dir", None) if game else None
        return (active_dir / "userlist.yaml") if active_dir else None

    @staticmethod
    def _parse_userlist(path: Path) -> dict:
        """Parse a minimal LOOT userlist.yaml into {'plugins': [...], 'groups': [...]}."""
        result: dict = {"plugins": [], "groups": []}
        if not path.is_file():
            return result
        text = path.read_text(encoding="utf-8")
        # Split into top-level sections; collect raw block per plugin/group entry
        current_section: str | None = None
        current_block: list[str] = []

        def _flush_block(section, block):
            if not block:
                return
            raw = "\n".join(block)
            entry: dict = {}
            # name — first line is "  - name: 'Foo.esp'" or "- name: 'Foo.esp'"
            m = re.match(r"^[\s\-]*name:\s*['\"]?(.*?)['\"]?\s*$", block[0])
            if m:
                entry["name"] = m.group(1)
            # scalar fields: group
            for line in block:
                mg = re.match(r"^\s*group:\s*['\"]?(.*?)['\"]?\s*$", line)
                if mg:
                    entry["group"] = mg.group(1)
            # list fields: before, after
            for field in ("before", "after"):
                pat = re.compile(r"^\s*" + field + r":\s*$")
                inline = re.compile(r"^\s*" + field + r":\s*\[(.+)\]\s*$")
                items: list[str] = []
                in_list = False
                for line in block:
                    if inline.match(line):
                        raw_items = inline.match(line).group(1)
                        items = [i.strip().strip("'\"") for i in raw_items.split(",") if i.strip()]
                        break
                    if pat.match(line):
                        in_list = True
                        continue
                    if in_list:
                        if re.match(r"^\s+\w[\w_]*\s*:", line):
                            # A new key at the same or lower indent — end of this list
                            in_list = False
                        else:
                            item_m = re.match(r"^\s*-\s*['\"]?(.*?)['\"]?\s*$", line)
                            if item_m:
                                items.append(item_m.group(1))
                if items:
                    # Deduplicate while preserving order
                    seen_items: list[str] = []
                    for item in items:
                        if item.lower() not in {s.lower() for s in seen_items}:
                            seen_items.append(item)
                    entry[field] = seen_items
            if entry.get("name"):
                result[section].append(entry)

        for line in text.splitlines():
            stripped = line.strip()
            if stripped == "plugins:":
                if current_section:
                    _flush_block(current_section, current_block)
                current_section = "plugins"
                current_block = []
            elif stripped == "groups:":
                if current_section:
                    _flush_block(current_section, current_block)
                current_section = "groups"
                current_block = []
            elif stripped.startswith("- name:") and current_section:
                if current_block:
                    _flush_block(current_section, current_block)
                current_block = [line]
            elif current_section and (line.startswith("  ") or line.startswith("\t")):
                current_block.append(line)

        if current_section and current_block:
            _flush_block(current_section, current_block)

        return result

    @staticmethod
    def _write_userlist(path: Path, data: dict):
        """Write a userlist dict back to YAML format."""
        lines = []

        def _quote(s: str) -> str:
            if "'" in s:
                escaped = s.replace('"', '\\"')
                return f'"{escaped}"'
            return f"'{s}'"

        plugins = data.get("plugins", [])
        groups = data.get("groups", [])

        if plugins:
            lines.append("plugins:")
            for entry in plugins:
                lines.append(f"  - name: {_quote(entry['name'])}")
                for field in ("before", "after"):
                    items = entry.get(field, [])
                    if items:
                        lines.append(f"    {field}:")
                        for item in items:
                            lines.append(f"      - {_quote(item)}")
                if entry.get("group"):
                    lines.append(f"    group: {_quote(entry['group'])}")

        if groups:
            if lines:
                lines.append("")
            lines.append("groups:")
            for entry in groups:
                lines.append(f"  - name: {_quote(entry['name'])}")
                after_items = entry.get("after", [])
                if after_items:
                    lines.append(f"    after:")
                    for item in after_items:
                        lines.append(f"      - {_quote(item)}")

        if lines:
            write_atomic_text(path, "\n".join(lines) + "\n")
        else:
            # Nothing left — remove the file so libloot doesn't choke on an empty document
            path.unlink(missing_ok=True)

    def _add_plugin_to_userlist(self, plugin_name: str, idx: int):
        """Show the inline userlist panel pre-populated for this plugin."""
        ul_path = self._get_userlist_path()
        if ul_path is None:
            self._log("No active profile — cannot edit userlist.")
            return

        data = self._parse_userlist(ul_path)
        existing_entry = next(
            (e for e in data["plugins"] if e.get("name", "").lower() == plugin_name.lower()),
            None,
        )

        # Always derive before/after from current load order position;
        # preserve saved group if there's an existing entry.
        entries = self._plugin_entries
        after_plugin  = entries[idx - 1].name if idx > 0 else ""
        before_plugin = entries[idx + 1].name if idx + 1 < len(entries) else ""

        self._ul_after_var.set(after_plugin)
        self._ul_before_var.set(before_plugin)
        self._ul_name_label.configure(text=plugin_name)
        self._userlist_panel_plugin = plugin_name
        self._userlist_panel_idx = idx
        self._ul_panel.grid()

    @staticmethod
    def _ul_parse_list(val: str) -> list[str]:
        return [p.strip() for p in val.split("|") if p.strip()]

    def _ul_save(self):
        plugin_name = self._userlist_panel_plugin
        ul_path = self._get_userlist_path()
        if not plugin_name or ul_path is None:
            self._ul_cancel()
            return

        data = self._parse_userlist(ul_path)
        data["plugins"] = [
            e for e in data["plugins"]
            if e.get("name", "").lower() != plugin_name.lower()
        ]

        # Preserve existing group when only updating before/after
        existing = next(
            (e for e in data["plugins"] if e.get("name", "").lower() == plugin_name.lower()),
            {},
        )
        entry: dict = {"name": plugin_name}
        before = self._ul_parse_list(self._ul_before_var.get())
        after  = self._ul_parse_list(self._ul_after_var.get())
        if after:
            entry["after"] = after
        if before:
            entry["before"] = before
        entry["group"] = existing.get("group") or "default"
        data["plugins"].append(entry)

        ul_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_userlist(ul_path, data)
        self._log(f"Userlist updated: {plugin_name}")
        self._refresh_userlist_set()
        self._predraw()
        self._ul_cancel()

    def _ul_cancel(self):
        self._userlist_panel_plugin = ""
        self._userlist_panel_idx = -1
        self._ul_panel.grid_remove()

    def _add_plugins_to_group(self, plugin_names: list[str]):
        """Show the inline group assignment panel for one or more plugins."""
        ul_path = self._get_userlist_path()
        if ul_path is None:
            self._log("No active profile — cannot assign group.")
            return

        data = self._parse_userlist(ul_path) if ul_path.is_file() else {"plugins": [], "groups": []}
        groups = [g["name"] for g in data.get("groups", []) if g.get("name")]
        if "default" not in groups:
            groups.insert(0, "default")

        # Use current group of first plugin as default selection
        first = next(
            (e for e in data["plugins"] if e.get("name", "").lower() == plugin_names[0].lower()),
            {},
        )
        current_group = first.get("group", "default")

        self._grp_menu.configure(values=groups)
        self._grp_var.set(current_group if current_group in groups else groups[0])
        label = plugin_names[0] if len(plugin_names) == 1 else f"{len(plugin_names)} plugins"
        self._grp_name_label.configure(text=label)
        self._group_panel_plugins = plugin_names
        self._grp_panel.grid()

    def _grp_save(self):
        plugin_names = getattr(self, "_group_panel_plugins", [])
        ul_path = self._get_userlist_path()
        if not plugin_names or ul_path is None:
            self._grp_cancel()
            return

        group = self._grp_var.get()
        data = self._parse_userlist(ul_path) if ul_path.is_file() else {"plugins": [], "groups": []}
        names_lower = {n.lower() for n in plugin_names}

        for plugin_name in plugin_names:
            existing = next(
                (e for e in data["plugins"] if e.get("name", "").lower() == plugin_name.lower()),
                None,
            )
            data["plugins"] = [
                e for e in data["plugins"]
                if e.get("name", "").lower() != plugin_name.lower()
            ]
            entry = dict(existing) if existing else {"name": plugin_name}
            entry["name"] = plugin_name
            entry["group"] = group
            data["plugins"].append(entry)

        ul_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_userlist(ul_path, data)
        self._log(f"Group assigned: {len(plugin_names)} plugin(s) → {group}")
        self._refresh_userlist_set()
        self._predraw()
        self._grp_cancel()

    def _grp_cancel(self):
        self._group_panel_plugins = []
        self._grp_panel.grid_remove()

    def _remove_plugin_from_userlist(self, plugin_name: str):
        self._remove_plugins_from_userlist([plugin_name])

    def _remove_plugins_from_userlist(self, plugin_names: list[str]):
        """Remove one or more plugin entries from userlist.yaml."""
        ul_path = self._get_userlist_path()
        if ul_path is None:
            return
        lower = {n.lower() for n in plugin_names}
        data = self._parse_userlist(ul_path)
        data["plugins"] = [e for e in data["plugins"] if e.get("name", "").lower() not in lower]
        self._write_userlist(ul_path, data)
        self._log(f"Removed from userlist: {len(plugin_names)} plugin(s)")
        self._refresh_userlist_set()
        self._predraw()
