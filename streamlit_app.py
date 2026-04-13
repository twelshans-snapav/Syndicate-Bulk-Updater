#!/usr/bin/env python3
# streamlit_app.py — Syndicate Bulk Updater (Streamlit web app)
#
# Run locally:  streamlit run streamlit_app.py
# Deploy:       push to GitHub, connect repo to share.streamlit.io

import json
import time
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

from syndicate_client import Client

st.set_page_config(
    page_title="Syndicate Bulk Updater",
    layout="wide",
    page_icon="📄",
)

# ── Session state init ────────────────────────────────────────────────────────

def _init():
    defaults: Dict[str, Any] = {
        "client": None,
        "authenticated": False,
        "current_folder_id": None,
        "folder_stack": [],        # [{"id": …, "name": …}, …]
        "subfolders": [],
        "docs": [],
        "docs_offset": 0,
        "docs_max": 50,
        "docs_search": "",
        "docs_has_next": False,
        "cls_name_cache": {},
        "log": [],
        # Bulk editor
        "bulk_open": False,
        "bulk_targets": [],
        "bulk_attrs": [],
        "attr_changes": [],
        "cls_roots": [],
        "cls_expanded": {},        # {cid: [child_nodes]}
        "cls_selected_nodes": [],  # [{"id": …, "name": …}]
        # Rename
        "rename_open": False,
        "rename_doc": None,
        # Reload trigger
        "docs_stale": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v
    if st.session_state.client is None:
        st.session_state.client = Client()

_init()

# ── Auto-authenticate from secrets (dev / Streamlit Cloud) ───────────────────
# Add username + password to .streamlit/secrets.toml to skip the login screen
# on page refresh. That file is gitignored and never committed.
if not st.session_state.authenticated:
    try:
        _u = st.secrets.get("username", "")
        _p = st.secrets.get("password", "")
        if _u and _p:
            do_auth(_u, _p)
    except Exception:
        pass  # No secrets file present — show login form normally

# ── Utilities ─────────────────────────────────────────────────────────────────

def log(msg: str):
    ts = time.strftime("%H:%M:%S")
    st.session_state.log.append(f"[{ts}] {msg}")
    if len(st.session_state.log) > 200:
        st.session_state.log = st.session_state.log[-200:]

def c() -> Client:
    return st.session_state.client

def summarize_attrs(lst: Any, limit: int = 100) -> str:
    parts = []
    if isinstance(lst, list):
        for a in lst:
            if isinstance(a, dict):
                parts.append(f"{a.get('name') or a.get('id')}={a.get('value')}")
    s = "; ".join(parts)
    return (s[: limit - 1] + "…") if len(s) > limit else s

def parse_values(values: Any) -> List[str]:
    if values is None:
        return []
    if isinstance(values, list):
        return [str(v) for v in values]
    if isinstance(values, str):
        s = values.strip()
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return [str(v) for v in parsed]
        except Exception:
            pass
        if "," in s:
            return [p.strip() for p in s.split(",") if p.strip()]
        return [s] if s else []
    return [str(values)]

# ── Auth ──────────────────────────────────────────────────────────────────────

def do_auth(username: str, password: str):
    try:
        c().authenticate("adiglobal", username, password)
        st.session_state.authenticated = True
        log("Authenticated.")
        load_folder("root", "root")
    except Exception as e:
        st.error(f"Authentication failed: {e}")
        log(f"Auth error: {e}")

def do_signout():
    st.session_state.client = Client()
    st.session_state.authenticated = False
    st.session_state.current_folder_id = None
    st.session_state.folder_stack = []
    st.session_state.subfolders = []
    st.session_state.docs = []
    log("Signed out.")

# ── Folder navigation ─────────────────────────────────────────────────────────

def load_folder(folder_id: Any, folder_name: str):
    try:
        subs = c().get_subfolders_page(folder_id, max_results=200, offset=0)
        st.session_state.subfolders = subs
        st.session_state.current_folder_id = folder_id
        st.session_state.docs_offset = 0
        log(f"Loaded {len(subs)} subfolder(s) for '{folder_name}'.")
        load_docs()
    except Exception as e:
        st.error(f"Folder error: {e}")
        log(f"Folder error: {e}")

def nav_into(folder_id: Any, folder_name: str):
    st.session_state.folder_stack.append({"id": folder_id, "name": folder_name})
    load_folder(folder_id, folder_name)

def nav_up():
    stack = st.session_state.folder_stack
    if len(stack) > 1:
        stack.pop()
        entry = stack[-1]
        load_folder(entry["id"], entry["name"])
    else:
        st.session_state.folder_stack = []
        load_folder("root", "root")

# ── Documents ─────────────────────────────────────────────────────────────────

def load_docs():
    fid = st.session_state.current_folder_id or "root"
    max_val = st.session_state.docs_max
    offset = st.session_state.docs_offset
    q = st.session_state.docs_search or None
    try:
        rows = c().get_items(fid, max_results=max_val, offset=offset, filterText=q)
        docs = [r for r in rows if str(r.get("class") or "").lower() == "document"]
        enriched = []
        for d in docs:
            if not d.get("customAttributes") or not d.get("classifications"):
                try:
                    det = c().get_document(d["id"], include_custom=True, include_classifications=True)
                    if isinstance(det, dict):
                        if det.get("customAttributes"):
                            d["customAttributes"] = det["customAttributes"]
                        if det.get("classifications"):
                            d["classifications"] = det["classifications"]
                except Exception:
                    pass
            for cl in d.get("classifications") or []:
                try:
                    st.session_state.cls_name_cache[int(cl["id"])] = str(cl.get("name") or "")
                except Exception:
                    pass
            enriched.append(d)
        st.session_state.docs = enriched
        st.session_state.docs_has_next = len(enriched) == max_val
        log(f"Loaded {len(enriched)} doc(s) (offset={offset}).")
    except Exception as e:
        st.error(f"Document load error: {e}")
        log(f"Docs error: {e}")

# ── Classification tree ───────────────────────────────────────────────────────

def cls_load_roots(filter_text: str = ""):
    q = filter_text.strip() or None
    try:
        if q:
            items = c().list_classifications(
                filterText=q, max_results=100, offset=0, orderBy=None, orderDirection=None
            )
        else:
            items = c().list_root_classifications()
        st.session_state.cls_roots = items
        st.session_state.cls_expanded = {}
        for item in items:
            try:
                st.session_state.cls_name_cache[int(item["id"])] = str(item.get("name") or "")
            except Exception:
                pass
        log(f"Loaded {len(items)} classification root(s).")
    except Exception as e:
        st.error(f"Classification load error: {e}")

def cls_toggle_expand(cid: int):
    expanded = st.session_state.cls_expanded
    if cid in expanded:
        del expanded[cid]
    else:
        try:
            children = c().list_class_children(cid)
            expanded[cid] = children
            for ch in children:
                try:
                    st.session_state.cls_name_cache[int(ch["id"])] = str(ch.get("name") or "")
                except Exception:
                    pass
        except Exception as e:
            st.error(f"Failed to load children: {e}")

def cls_add_node(cid: int, nm: str):
    existing = {x["id"] for x in st.session_state.cls_selected_nodes}
    if cid not in existing:
        st.session_state.cls_selected_nodes.append({"id": cid, "name": nm})

def render_cls_tree(items: List[Dict[str, Any]], depth: int = 0, key_prefix: str = "root"):
    for node in items:
        try:
            cid = int(node.get("id"))
            nm = str(node.get("name") or cid)
            has_children = bool(node.get("hasChildren"))
            is_expanded = cid in st.session_state.cls_expanded
        except Exception:
            continue

        indent = "\u3000" * depth  # em-space indentation
        col_label, col_add = st.columns([9, 1])

        with col_label:
            if has_children:
                arrow = "▼" if is_expanded else "▶"
                if st.button(
                    f"{indent}{arrow} {nm} ({cid})",
                    key=f"cls_toggle_{key_prefix}_{cid}",
                    use_container_width=True,
                ):
                    cls_toggle_expand(cid)
                    st.rerun()
            else:
                st.markdown(
                    f'<div style="padding:4px 0;font-size:14px">{indent}&nbsp;&nbsp;{nm} ({cid})</div>',
                    unsafe_allow_html=True,
                )

        with col_add:
            if st.button("＋", key=f"cls_add_{key_prefix}_{cid}", help=f"Add {nm}"):
                cls_add_node(cid, nm)
                st.rerun()

        if is_expanded:
            render_cls_tree(
                st.session_state.cls_expanded.get(cid, []),
                depth=depth + 1,
                key_prefix=f"{key_prefix}_{cid}",
            )

# ── Bulk editor dialog ────────────────────────────────────────────────────────

def _clear_bulk_state():
    st.session_state.bulk_open = False
    st.session_state.attr_changes = []
    st.session_state.cls_roots = []
    st.session_state.cls_expanded = {}
    st.session_state.cls_selected_nodes = []


def _run_bulk(targets: List[Dict], attr_edits: List[Dict], cls_ids: List[int], replace_all: bool):
    cls_cache = st.session_state.cls_name_cache

    def names_for(ids):
        return [f"{i}({cls_cache.get(i, '')})" for i in ids]

    total = len(targets)
    succeeded = 0
    errors: List[str] = []
    progress = st.progress(0, text="Starting…")

    for i, t in enumerate(targets):
        did, dname = t["id"], t["name"]
        progress.progress(i / total, text=f"Updating {dname} ({i + 1}/{total})…")
        try:
            before = c().get_document(did, include_custom=True, include_classifications=True)
            ver = (before.get("latestVersion") or {}).get("id")
            if not ver:
                raise RuntimeError(f"No latestVersion.id for doc {did}")
            b_cls: List[int] = []
            for cl in before.get("classifications") or []:
                try:
                    b_cls.append(int(cl["id"]))
                    cls_cache[int(cl["id"])] = str(cl.get("name") or "")
                except Exception:
                    pass
            for e in attr_edits:
                c().post_version_attr(ver, e["id"], e["value"])
            if cls_ids:
                target_ids = cls_ids if replace_all else sorted(set(b_cls) | set(cls_ids))
                c().set_document_classifications(did, target_ids, replace_all=replace_all)
            succeeded += 1
        except Exception as e:
            errors.append(f"• {dname} (id {did}): {e}")

    progress.progress(1.0, text="Done")

    summary = (
        f"**Bulk edit complete.**\n\n"
        f"- Processed: {total}  \n"
        f"- Succeeded: {succeeded}  \n"
    )
    if errors:
        summary += f"- Failed: {len(errors)}  \n"
    if attr_edits:
        summary += f"- Attributes set: {', '.join(e['name'] for e in attr_edits)}  \n"
    if cls_ids:
        mode = "replaced all with" if replace_all else "merged in"
        summary += f"- Classifications ({mode}): {', '.join(names_for(cls_ids))}"

    st.success(summary)
    for err in errors:
        st.error(err)

    log(f"Bulk edit: {succeeded}/{total} succeeded.")
    _clear_bulk_state()
    st.session_state.docs_stale = True


@st.dialog("Bulk Edit", width="large")
def bulk_editor_dialog():
    targets: List[Dict] = st.session_state.bulk_targets
    attrs: List[Dict] = st.session_state.bulk_attrs

    st.write(f"**{len(targets)} document(s) selected**")
    with st.expander("Target documents"):
        st.dataframe(
            pd.DataFrame([{"id": t["id"], "name": t["name"]} for t in targets]),
            hide_index=True,
            use_container_width=True,
        )

    tab_attr, tab_cls = st.tabs(["Custom Attributes", "Classifications"])

    # ── Attributes tab ─────────────────────────────────────────────────────
    with tab_attr:
        def_by_id: Dict[int, Dict] = {}
        id_by_name: Dict[str, int] = {}
        for d in attrs:
            try:
                did = int(d.get("id"))
                nm = str(d.get("name") or "").strip()
                def_by_id[did] = d
                if nm:
                    id_by_name[nm] = did
            except Exception:
                pass
        names_sorted = sorted(id_by_name.keys(), key=str.lower)

        c1, c2, c3 = st.columns([3, 3, 1])
        with c1:
            attr_name = st.selectbox("Attribute", [""] + names_sorted, key="dlg_attr_name")

        val_input: Any = ""
        if attr_name:
            aid = id_by_name.get(attr_name)
            d = def_by_id.get(aid) or {}
            atype = (d.get("type") or "string").lower()
            vals = parse_values(d.get("values"))
            with c2:
                if atype == "choice" and vals:
                    val_input = st.selectbox("Value", [""] + vals, key="dlg_attr_val")
                elif atype == "boolean":
                    val_input = st.selectbox("Value", ["", "Yes", "No"], key="dlg_attr_val")
                else:
                    val_input = st.text_input("Value", key="dlg_attr_val")
        with c3:
            st.write("")
            st.write("")
            if st.button("Add", key="dlg_add_attr"):
                if attr_name:
                    aid = id_by_name.get(attr_name)
                    if isinstance(aid, int):
                        st.session_state.attr_changes.append(
                            {"id": aid, "name": attr_name, "value": val_input or ""}
                        )
                        st.rerun()

        if st.session_state.attr_changes:
            st.write("**Pending changes:**")
            attr_df = pd.DataFrame(st.session_state.attr_changes)
            sel = st.dataframe(
                attr_df,
                hide_index=True,
                use_container_width=True,
                on_select="rerun",
                selection_mode="multi-row",
                key="dlg_attr_table",
            )
            if st.button("Remove Selected", key="dlg_remove_attr"):
                idxs = set(sel.selection.rows)
                st.session_state.attr_changes = [
                    r for i, r in enumerate(st.session_state.attr_changes) if i not in idxs
                ]
                st.rerun()
        else:
            st.info("No attribute changes queued. Select an attribute above and click Add.")

    # ── Classifications tab ─────────────────────────────────────────────────
    with tab_cls:
        if not st.session_state.cls_roots:
            cls_load_roots()

        col_f, col_s = st.columns([4, 1])
        with col_f:
            cls_filter = st.text_input("Filter", key="dlg_cls_filter", placeholder="Type to filter…")
        with col_s:
            st.write("")
            st.write("")
            if st.button("Search", key="dlg_cls_search"):
                cls_load_roots(cls_filter)
                st.rerun()

        col_tree, col_sel = st.columns([3, 2])
        with col_tree:
            st.write("**Tree** — click ▶ to expand, ＋ to select")
            if st.session_state.cls_roots:
                render_cls_tree(st.session_state.cls_roots, key_prefix="dlg")
            else:
                st.caption("No classifications loaded.")

        with col_sel:
            st.write("**Selected**")
            if st.session_state.cls_selected_nodes:
                sel_df = pd.DataFrame(st.session_state.cls_selected_nodes)
                sel_tbl = st.dataframe(
                    sel_df,
                    hide_index=True,
                    use_container_width=True,
                    on_select="rerun",
                    selection_mode="multi-row",
                    key="dlg_cls_sel_table",
                )
                if st.button("Remove Selected", key="dlg_cls_remove"):
                    idxs = set(sel_tbl.selection.rows)
                    st.session_state.cls_selected_nodes = [
                        r
                        for i, r in enumerate(st.session_state.cls_selected_nodes)
                        if i not in idxs
                    ]
                    st.rerun()
            else:
                st.caption("Click ＋ on a tree node to add it here.")

    # ── Apply / Cancel ──────────────────────────────────────────────────────
    st.divider()
    replace_all = st.checkbox(
        "Replace ALL existing classifications (unchecked = merge/add)",
        value=False,
        key="dlg_replace_all",
    )
    col_cancel, col_apply = st.columns(2)
    with col_cancel:
        if st.button("Cancel", use_container_width=True, key="dlg_cancel"):
            _clear_bulk_state()
            st.rerun()
    with col_apply:
        n = len(targets)
        if st.button(
            f"Apply to {n} document(s)",
            type="primary",
            use_container_width=True,
            key="dlg_apply",
        ):
            attr_edits = st.session_state.attr_changes
            cls_ids = [x["id"] for x in st.session_state.cls_selected_nodes]
            if not attr_edits and not cls_ids:
                st.warning("Add at least one attribute or classification change.")
            else:
                _run_bulk(targets, attr_edits, cls_ids, replace_all)


# ── Rename dialog ─────────────────────────────────────────────────────────────

@st.dialog("Rename Document")
def rename_dialog():
    doc = st.session_state.rename_doc
    st.caption(f"Document ID: {doc['id']}")
    new_name = st.text_input("Name", value=doc["name"], key="rename_input")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Cancel", use_container_width=True, key="rename_cancel"):
            st.session_state.rename_open = False
            st.rerun()
    with col2:
        if st.button("Apply", type="primary", use_container_width=True, key="rename_apply"):
            if not new_name.strip():
                st.warning("Name cannot be empty.")
            elif new_name.strip() == doc["name"]:
                st.session_state.rename_open = False
                st.rerun()
            else:
                try:
                    result = c().update_document(doc["id"], new_name.strip())
                    updated = result.get("name", new_name.strip())
                    for d in st.session_state.docs:
                        if str(d.get("id")) == str(doc["id"]):
                            d["name"] = updated
                            break
                    log(f"Renamed {doc['id']}: '{doc['name']}' → '{updated}'")
                    st.session_state.rename_open = False
                    st.rerun()
                except Exception as e:
                    st.error(f"Rename failed: {e}")

# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("Syndicate\nBulk Updater")
    st.divider()

    if not st.session_state.authenticated:
        with st.form("auth_form"):
            st.subheader("Sign In")
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            if st.form_submit_button("Authenticate", use_container_width=True):
                if username and password:
                    do_auth(username, password)
                    st.rerun()
                else:
                    st.warning("Enter username and password.")
    else:
        st.success("✓ Authenticated")
        if st.button("Sign Out", use_container_width=True):
            do_signout()
            st.rerun()

        st.divider()
        st.subheader("Folders")

        stack = st.session_state.folder_stack
        if stack:
            path_names = ["root"] + [s["name"] for s in stack]
            st.caption(" / ".join(path_names))
            if st.button("⬆ Up", use_container_width=True):
                nav_up()
                st.rerun()
        else:
            st.caption("root")

        for sf in st.session_state.subfolders:
            sf_id = sf.get("id")
            sf_name = str(sf.get("name") or sf_id)
            if st.button(f"📁 {sf_name}", key=f"sf_{sf_id}", use_container_width=True):
                nav_into(sf_id, sf_name)
                st.rerun()

# ── Main area ─────────────────────────────────────────────────────────────────

if not st.session_state.authenticated:
    st.info("👈 Sign in using the sidebar to get started.")
    st.stop()

st.subheader("Documents")

# Search / filter bar
col_s, col_m, col_a, col_c = st.columns([4, 1, 1, 1])
with col_s:
    search_input = st.text_input(
        "search",
        value=st.session_state.docs_search,
        label_visibility="collapsed",
        placeholder="Search documents…",
        key="search_box",
    )
with col_m:
    max_input = st.number_input(
        "max",
        min_value=1,
        max_value=500,
        value=st.session_state.docs_max,
        label_visibility="collapsed",
        key="max_box",
    )
with col_a:
    if st.button("Apply", use_container_width=True):
        st.session_state.docs_search = search_input
        st.session_state.docs_max = int(max_input)
        st.session_state.docs_offset = 0
        load_docs()
        st.rerun()
with col_c:
    if st.button("Clear", use_container_width=True):
        st.session_state.docs_search = ""
        st.session_state.docs_offset = 0
        load_docs()
        st.rerun()

# Documents dataframe
docs = st.session_state.docs
if docs:
    rows = []
    for d in docs:
        fmt = d.get("format") or (d.get("latestVersion") or {}).get("format", "")
        ca = summarize_attrs(d.get("customAttributes"))
        cl = ", ".join(
            str(x.get("name") or x.get("id")) for x in (d.get("classifications") or [])
        )
        rows.append(
            {
                "id": d.get("id"),
                "name": d.get("name"),
                "format": fmt,
                "dateUpdated": d.get("dateUpdated"),
                "customAttributes": ca,
                "classifications": cl,
            }
        )
    df = pd.DataFrame(rows)
    selection = st.dataframe(
        df,
        hide_index=True,
        use_container_width=True,
        on_select="rerun",
        selection_mode="multi-row",
        key="docs_table",
    )
    selected_indices = selection.selection.rows
    selected_docs = [docs[i] for i in selected_indices]
else:
    selected_docs = []
    if st.session_state.current_folder_id:
        st.info("No documents in this folder.")
    else:
        st.info("Select a folder from the sidebar to view documents.")

# Action bar
col_prev, col_next, col_edit, col_rename = st.columns([1, 1, 3, 2])
offset = st.session_state.docs_offset
max_v = st.session_state.docs_max

with col_prev:
    if st.button("← Prev", disabled=(offset == 0), use_container_width=True):
        st.session_state.docs_offset = max(0, offset - max_v)
        load_docs()
        st.rerun()

with col_next:
    if st.button("Next →", disabled=(not st.session_state.docs_has_next), use_container_width=True):
        st.session_state.docs_offset = offset + max_v
        load_docs()
        st.rerun()

with col_edit:
    n_sel = len(selected_docs)
    label = f"Edit Selected ({n_sel})" if n_sel else "Edit Selected"
    if st.button(label, disabled=(n_sel == 0), type="primary", use_container_width=True):
        targets = [{"id": d["id"], "name": d["name"]} for d in selected_docs]
        try:
            attrs = c().list_all_custom_attributes_safe(page_size=200)
        except Exception:
            attrs = []
        _clear_bulk_state()
        st.session_state.bulk_targets = targets
        st.session_state.bulk_attrs = attrs
        st.session_state.bulk_open = True

with col_rename:
    if st.button("Rename…", disabled=(len(selected_docs) != 1), use_container_width=True):
        d = selected_docs[0]
        st.session_state.rename_doc = {"id": d["id"], "name": d["name"]}
        st.session_state.rename_open = True

if docs:
    st.caption(f"Showing {offset + 1}–{offset + len(docs)}")

# ── Open dialogs if flagged ───────────────────────────────────────────────────

if st.session_state.get("bulk_open"):
    bulk_editor_dialog()

if st.session_state.get("rename_open"):
    rename_dialog()

# Reload docs once the bulk editor has closed
if st.session_state.docs_stale and not st.session_state.get("bulk_open"):
    st.session_state.docs_stale = False
    load_docs()
    st.rerun()

# ── Log ───────────────────────────────────────────────────────────────────────

with st.expander("Log"):
    lines = st.session_state.log
    if lines:
        st.text("\n".join(reversed(lines[-50:])))
    else:
        st.caption("No activity yet.")
