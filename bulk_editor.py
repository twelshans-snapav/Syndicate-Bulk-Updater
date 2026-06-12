#!/usr/bin/env python3
# bulk_editor.py
# BulkEditorWindow — modal dialog for editing attributes and classifications on multiple documents

import json
import threading
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

import tkinter as tk
from tkinter import ttk, messagebox

from syndicate_client import Client


def _remove_selected_rows(tree: ttk.Treeview) -> None:
    for it in tree.selection():
        tree.delete(it)


class BulkEditorWindow(tk.Toplevel):
    def __init__(
        self,
        master: tk.Tk,
        client: Client,
        targets: List[Dict[str, Any]],
        defs_attrs: List[Dict[str, Any]],
        *,
        cls_name_cache: Dict[int, str],
        log_fn: Callable[[str], None],
        on_doc_updated: Callable[[Any, Dict[str, Any]], None],
        start_busy: Optional[Callable[[str], None]] = None,
        stop_busy: Optional[Callable[[], None]] = None,
        reset_activity: Optional[Callable[[], None]] = None,
    ):
        super().__init__(master)
        self.client = client
        self.targets = targets
        self.cls_name_cache = cls_name_cache
        self.log = log_fn
        self.on_doc_updated = on_doc_updated
        self._start_busy = start_busy or (lambda msg: None)
        self._stop_busy = stop_busy or (lambda: None)
        self._reset_activity = reset_activity or (lambda: None)
        self._cls_loaded = False

        count = len(targets)
        self.title("Bulk Edit — " + str(count) + " document(s)")
        self.geometry("1360x880")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned.grid(row=0, column=0, sticky='nsew', padx=6, pady=(6, 0))

        # --- Left: target documents ---
        left = ttk.Frame(paned)
        paned.add(left, weight=1)
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)

        ttk.Label(left, text="Target documents").grid(row=0, column=0, sticky='w', padx=8, pady=(8, 2))
        tgt_frame = ttk.Frame(left)
        tgt_frame.grid(row=1, column=0, sticky='nsew', padx=8, pady=8)
        tgt_frame.rowconfigure(0, weight=1)
        tgt_frame.columnconfigure(0, weight=1)

        tgt = ttk.Treeview(tgt_frame, columns=("id", "name"), show='headings')
        tgt.heading("id", text="id")
        tgt.column("id", width=90, minwidth=60, anchor=tk.W)
        tgt.heading("name", text="name")
        tgt.column("name", width=260, minwidth=80, anchor=tk.W)
        tgt_vsb = ttk.Scrollbar(tgt_frame, orient=tk.VERTICAL, command=tgt.yview)
        tgt.configure(yscrollcommand=tgt_vsb.set)
        tgt_vsb.grid(row=0, column=1, sticky='ns')
        tgt.grid(row=0, column=0, sticky='nsew')
        for t in targets:
            tgt.insert('', tk.END, values=(t['id'], t['name']))

        # --- Right: notebook ---
        self._notebook = ttk.Notebook(paned)
        paned.add(self._notebook, weight=2)

        tab_attr = ttk.Frame(self._notebook)
        self._notebook.add(tab_attr, text='Custom Attributes')
        self._build_attr_tab(tab_attr, defs_attrs)

        tab_cls = ttk.Frame(self._notebook)
        self._notebook.add(tab_cls, text='Classifications (Tree)')
        self._build_cls_tree_tab(tab_cls)

        self._notebook.bind('<<NotebookTabChanged>>', self._on_tab_changed)

        # --- Bottom bar ---
        bottom = ttk.Frame(self)
        bottom.grid(row=1, column=0, sticky='ew', padx=10, pady=(4, 10))
        bottom.columnconfigure(2, weight=1)

        self.cls_replace_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(bottom, text='Replace ALL existing classifications (unchecked = merge/add)', variable=self.cls_replace_var).grid(row=0, column=0, padx=(4, 12), sticky='w')

        prog = ttk.Progressbar(bottom, mode='determinate', maximum=max(1, len(targets)))
        prog.grid(row=0, column=2, sticky='ew', padx=(0, 8))
        prog_lbl = ttk.Label(bottom, text="Ready")
        prog_lbl.grid(row=0, column=3, padx=(0, 12), sticky='w')

        ttk.Button(bottom, text="Cancel", command=self.destroy).grid(row=0, column=4, padx=4)
        ttk.Button(bottom, text="Apply to " + str(count) + " document(s)", command=lambda: on_apply()).grid(row=0, column=5, padx=(4, 6))

        def on_apply():
            edits_attrs = self._collect_attr_edits()
            sel_cls_ids = self._collect_cls_selected_ids()
            replace_all = bool(self.cls_replace_var.get())
            if not edits_attrs and not sel_cls_ids:
                messagebox.showinfo("No changes", "Add at least one attribute or classification change.")
                return

            def names_for_ids(ids: List[int]) -> List[str]:
                out = []
                for cid in ids:
                    nm = self.cls_name_cache.get(cid)
                    out.append(f"{cid}({nm})" if nm else str(cid))
                return out

            def worker():
                try:
                    total = len(targets)
                    done = 0
                    succeeded = 0
                    errors: List[str] = []
                    for t in targets:
                        did = t['id']
                        dname = t['name']
                        self.after(0, lambda doc=did, d=done, tot=total: (
                            prog_lbl.config(text=f"Updating doc {doc} ({d + 1}/{tot})…"),
                            prog.__setitem__('value', d),
                        ))
                        try:
                            before = self.client.get_document(did, include_custom=True, include_classifications=True)
                            ver = (before.get('latestVersion') or {}).get('id')
                            if not ver:
                                raise RuntimeError("No latestVersion.id for doc " + str(did))
                            b_cls_ids = []
                            for c in (before.get('classifications') or []):
                                try:
                                    cid = int(c.get('id'))
                                    b_cls_ids.append(cid)
                                    nm = str(c.get('name') or '')
                                    if nm:
                                        self.cls_name_cache[cid] = nm
                                except Exception:
                                    pass
                            # Attributes
                            for e in edits_attrs:
                                self.log(f"POST version attr: ver={ver} attr={e['id']} value={e['value']}")
                                self.client.post_version_attr(ver, e['id'], e['value'])
                            # Classifications
                            if sel_cls_ids:
                                target_ids = sel_cls_ids if replace_all else sorted(set(b_cls_ids) | set(sel_cls_ids))
                                self.log("POST classifications: doc=" + str(did) + " ids=[" + ", ".join(names_for_ids(target_ids)) + "] " + ("(replaceAll)" if replace_all else "(merge->replaceAll)"))
                                self.client.set_document_classifications(did, target_ids, replace_all=replace_all)
                            after = self.client.get_document(did, include_custom=True, include_classifications=True)
                            a_cls_ids = []
                            for c in (after.get('classifications') or []):
                                try:
                                    cid = int(c.get('id'))
                                    a_cls_ids.append(cid)
                                    nm = str(c.get('name') or '')
                                    if nm:
                                        self.cls_name_cache[cid] = nm
                                except Exception:
                                    pass
                            if sel_cls_ids:
                                self.log("Doc " + str(did) + " — Classifications: BEFORE=[" + ", ".join(names_for_ids(b_cls_ids)) + "] -> AFTER=[" + ", ".join(names_for_ids(a_cls_ids)) + "]")
                            self.after(0, lambda d=did, a=after: self.on_doc_updated(d, a))
                            succeeded += 1
                            self._reset_activity()
                        except Exception as e:
                            errors.append(f"• {dname} (id {did}): {e}")
                            self.log("Update error (doc " + str(did) + "): " + str(e))
                        finally:
                            done += 1
                            self.after(0, lambda d=done: prog.__setitem__('value', d))

                    # Build summary message
                    summary_lines = [f"Bulk edit complete.\n"]
                    summary_lines.append(f"  Documents processed:  {total}")
                    summary_lines.append(f"  Succeeded:            {succeeded}")
                    if errors:
                        summary_lines.append(f"  Failed:               {len(errors)}")
                    if edits_attrs:
                        attr_names = ", ".join(e['name'] for e in edits_attrs)
                        summary_lines.append(f"\n  Attributes set:  {attr_names}")
                    if sel_cls_ids:
                        cls_names = ", ".join(names_for_ids(sel_cls_ids))
                        mode = "replaced all with" if replace_all else "merged in"
                        summary_lines.append(f"  Classifications: {mode} [{cls_names}]")
                    if errors:
                        summary_lines.append("\nErrors:")
                        summary_lines.extend(errors)
                    summary = "\n".join(summary_lines)

                    def _finish(msg=summary):
                        prog_lbl.config(text="Done")
                        messagebox.showinfo("Bulk Edit Complete", msg)
                        self.destroy()
                    self.after(0, _finish)
                except Exception as e:
                    _err = str(e)
                    self.after(0, lambda err=_err: (
                        messagebox.showerror("Bulk Edit", err),
                        self.log("Bulk update error: " + err),
                    ))
            threading.Thread(target=worker, daemon=True).start()

    def _on_tab_changed(self, event=None):
        selected = self._notebook.tab(self._notebook.select(), 'text')
        if selected == 'Classifications (Tree)' and not self._cls_loaded:
            self._cls_loaded = True
            self._cls_search_roots('')

    # ---------- Attributes tab ----------
    def _build_attr_tab(self, parent: tk.Widget, defs: List[Dict[str, Any]]):
        frm = ttk.Frame(parent)
        frm.pack(fill=tk.BOTH, expand=True)
        frm.columnconfigure(1, weight=1)
        frm.rowconfigure(3, weight=1)

        def_by_id: Dict[int, Dict[str, Any]] = {}
        id_by_name: Dict[str, int] = {}
        for d in defs:
            try:
                did = int(d.get('id'))
                nm = str(d.get('name') or '').strip()
                def_by_id[did] = d
                if nm:
                    id_by_name[nm] = did
            except Exception:
                pass
        names_sorted = sorted(list(id_by_name.keys()), key=lambda s: s.lower())

        # Row 0: attribute name selector + filter
        ttk.Label(frm, text="Attribute Name").grid(row=0, column=0, sticky='w', padx=8, pady=(8, 4))
        name_var = tk.StringVar()
        name_combo = ttk.Combobox(frm, textvariable=name_var, values=names_sorted, state='readonly')
        name_combo.grid(row=0, column=1, sticky='ew', padx=4, pady=(8, 4))

        ttk.Label(frm, text="Filter").grid(row=0, column=2, sticky='w', padx=(12, 4), pady=(8, 4))
        filt_var = tk.StringVar()
        ttk.Entry(frm, textvariable=filt_var).grid(row=0, column=3, sticky='ew', padx=4, pady=(8, 4))
        frm.columnconfigure(3, weight=1)
        ttk.Button(frm, text="Load Names", command=lambda: on_fetch_names()).grid(row=0, column=4, sticky='w', padx=(4, 8), pady=(8, 4))

        # Row 1: value selector + add button
        ttk.Label(frm, text="Value").grid(row=1, column=0, sticky='w', padx=8, pady=4)
        dyn_val_var: Optional[tk.Variable] = None
        dyn_widget: Optional[Union[ttk.Entry, ttk.Combobox]] = None

        def reset_dyn():
            nonlocal dyn_val_var, dyn_widget
            if dyn_widget is not None:
                try:
                    dyn_widget.destroy()
                except Exception:
                    pass
            dyn_val_var = None
            dyn_widget = None

        def on_attr_selected(*_):
            nonlocal dyn_val_var, dyn_widget
            reset_dyn()
            nm = (name_var.get() or '').strip()
            if not nm:
                return
            aid = id_by_name.get(nm)
            d = def_by_id.get(aid) or {}
            atype = (d.get('type') or 'string')
            vals = self._parse_values_field(d.get('values'))
            t = (atype or '').lower()
            if t == 'choice' and vals:
                v = tk.StringVar()
                cb = ttk.Combobox(frm, textvariable=v, values=[''] + vals, state='readonly')
                cb.grid(row=1, column=1, sticky='ew', padx=4)
                dyn_val_var, dyn_widget = v, cb
            elif t == 'boolean':
                v = tk.StringVar()
                cb = ttk.Combobox(frm, textvariable=v, values=['Yes', 'No'], state='readonly')
                cb.grid(row=1, column=1, sticky='ew', padx=4)
                dyn_val_var, dyn_widget = v, cb
            else:
                v = tk.StringVar()
                ent = ttk.Entry(frm, textvariable=v)
                ent.grid(row=1, column=1, sticky='ew', padx=4)
                dyn_val_var, dyn_widget = v, ent

        name_combo.bind('<<ComboboxSelected>>', on_attr_selected)
        ttk.Button(frm, text="Add Attribute Change", command=lambda: add_attr_change()).grid(row=1, column=4, sticky='e', padx=(4, 8), pady=4)

        def on_fetch_names():
            q = (filt_var.get() or '').strip() or None
            try:
                items = self.client.list_custom_attributes(filterText=q, max_results=50, offset=0, orderBy=None, orderDirection=None)
            except Exception as e:
                messagebox.showerror("Lookup", "Attribute filter lookup failed: " + str(e))
                return
            for a in items:
                try:
                    did = int(a.get('id'))
                    nm = str(a.get('name') or '').strip()
                    def_by_id[did] = a
                    if nm:
                        id_by_name[nm] = did
                except Exception:
                    pass
            names = sorted(list(id_by_name.keys()), key=lambda s: s.lower())
            name_combo['values'] = names
            self.log("Loaded " + str(len(items)) + " attribute name(s) for filter " + str(q))

        # Row 2: label
        ttk.Label(frm, text="Pending attribute changes").grid(row=2, column=0, columnspan=5, sticky='w', padx=8, pady=(8, 2))

        # Row 3: treeview with scrollbars
        attr_frame = ttk.Frame(frm)
        attr_frame.grid(row=3, column=0, columnspan=5, sticky='nsew', padx=8, pady=(0, 4))
        attr_frame.rowconfigure(0, weight=1)
        attr_frame.columnconfigure(0, weight=1)

        self.attr_changes = ttk.Treeview(attr_frame, columns=("id", "name", "value"), show='headings')
        for c, w in [("id", 80), ("name", 260), ("value", 360)]:
            self.attr_changes.heading(c, text=c)
            self.attr_changes.column(c, width=w, minwidth=50, anchor=tk.W)
        attr_vsb = ttk.Scrollbar(attr_frame, orient=tk.VERTICAL, command=self.attr_changes.yview)
        attr_hsb = ttk.Scrollbar(attr_frame, orient=tk.HORIZONTAL, command=self.attr_changes.xview)
        self.attr_changes.configure(yscrollcommand=attr_vsb.set, xscrollcommand=attr_hsb.set)
        attr_vsb.grid(row=0, column=1, sticky='ns')
        attr_hsb.grid(row=1, column=0, sticky='ew')
        self.attr_changes.grid(row=0, column=0, sticky='nsew')

        # Row 4: remove button
        ttk.Button(frm, text="Remove Selected", command=lambda: _remove_selected_rows(self.attr_changes)).grid(row=4, column=4, sticky='e', padx=(4, 8), pady=(0, 8))

        def add_attr_change():
            nm = (name_var.get() or '').strip()
            if not nm:
                messagebox.showinfo("Add", "Pick an attribute name first (use Load Names if list is empty).")
                return
            aid = id_by_name.get(nm)
            if not isinstance(aid, int):
                messagebox.showerror("Add", "Unknown attribute name: " + nm)
                return
            val = ''
            if dyn_val_var is not None:
                try:
                    val = dyn_val_var.get()
                except Exception:
                    val = ''
            self.attr_changes.insert('', tk.END, values=(aid, nm, val))
            try:
                name_var.set('')
            except Exception:
                pass

    @staticmethod
    def _parse_values_field(values: Any) -> List[str]:
        if values is None: return []
        if isinstance(values, list): return [str(v) for v in values]
        if isinstance(values, str):
            s = values.strip()
            try:
                parsed = json.loads(s)
                if isinstance(parsed, list):
                    return [str(v) for v in parsed]
            except Exception:
                pass
            if ',' in s:
                return [p.strip() for p in s.split(',') if p.strip()]
            return [s] if s else []
        return [str(values)]

    def _collect_attr_edits(self) -> List[Dict[str, Any]]:
        edits: List[Dict[str, Any]] = []
        tree = getattr(self, 'attr_changes', None)
        if not tree:
            return edits
        for it in tree.get_children(''):
            vals = tree.item(it, 'values')
            try:
                aid = int(vals[0])
            except Exception:
                continue
            edits.append({"id": aid, "name": vals[1], "value": vals[2]})
        return edits

    # ---------- Classifications TREE tab ----------
    def _build_cls_tree_tab(self, parent: tk.Widget):
        frm = ttk.Frame(parent)
        frm.pack(fill=tk.BOTH, expand=True)
        frm.rowconfigure(1, weight=1)
        frm.columnconfigure(1, weight=1)

        # Toolbar: filter + remaining action buttons
        ttk.Label(frm, text="Filter").grid(row=0, column=0, sticky='w', padx=8, pady=(8, 4))
        self.cls_filter_var = tk.StringVar()
        filt_entry = ttk.Entry(frm, textvariable=self.cls_filter_var)
        filt_entry.grid(row=0, column=1, sticky='ew', padx=4, pady=(8, 4))
        filt_entry.bind('<Return>', lambda e: self._cls_search_roots(self.cls_filter_var.get()))
        ttk.Button(frm, text="Search", command=lambda: self._cls_search_roots(self.cls_filter_var.get())).grid(row=0, column=2, padx=4, pady=(8, 4))
        ttk.Button(frm, text="Expand Selected", command=lambda: self._cls_expand_selected()).grid(row=0, column=3, padx=4, pady=(8, 4))
        ttk.Button(frm, text="Add Selected Node", command=lambda: self._cls_add_selected_node()).grid(row=0, column=4, padx=(4, 8), pady=(8, 4))

        # Horizontal pane: tree on left, selected on right
        pan = ttk.PanedWindow(frm, orient=tk.HORIZONTAL)
        pan.grid(row=1, column=0, columnspan=5, sticky='nsew', padx=8, pady=(0, 6))

        left = ttk.Frame(pan)
        pan.add(left, weight=3)
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)
        ttk.Label(left, text="Classification tree").grid(row=0, column=0, sticky='w')

        cls_tree_frame = ttk.Frame(left)
        cls_tree_frame.grid(row=1, column=0, sticky='nsew')
        cls_tree_frame.rowconfigure(0, weight=1)
        cls_tree_frame.columnconfigure(0, weight=1)

        self.cls_tree = ttk.Treeview(cls_tree_frame, show='tree')
        cls_vsb = ttk.Scrollbar(cls_tree_frame, orient=tk.VERTICAL, command=self.cls_tree.yview)
        self.cls_tree.configure(yscrollcommand=cls_vsb.set)
        cls_vsb.grid(row=0, column=1, sticky='ns')
        self.cls_tree.grid(row=0, column=0, sticky='nsew')
        self.cls_tree_ids: Dict[str, int] = {}
        self.cls_tree.bind('<<TreeviewOpen>>', lambda e: self._cls_on_open())
        self.cls_tree.bind('<Double-1>', lambda e: self._cls_on_double(e))

        right = ttk.Frame(pan)
        pan.add(right, weight=2)
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)
        ttk.Label(right, text="Selected classifications").grid(row=0, column=0, sticky='w')

        cls_sel_frame = ttk.Frame(right)
        cls_sel_frame.grid(row=1, column=0, sticky='nsew')
        cls_sel_frame.rowconfigure(0, weight=1)
        cls_sel_frame.columnconfigure(0, weight=1)

        self.cls_selected = ttk.Treeview(cls_sel_frame, columns=("id", "name"), show='headings')
        self.cls_selected.heading('id', text='id')
        self.cls_selected.column('id', width=90, minwidth=50, anchor=tk.W)
        self.cls_selected.heading('name', text='name')
        self.cls_selected.column('name', width=260, minwidth=80, anchor=tk.W)
        sel_vsb = ttk.Scrollbar(cls_sel_frame, orient=tk.VERTICAL, command=self.cls_selected.yview)
        self.cls_selected.configure(yscrollcommand=sel_vsb.set)
        sel_vsb.grid(row=0, column=1, sticky='ns')
        self.cls_selected.grid(row=0, column=0, sticky='nsew')

        ttk.Button(right, text="Remove Selected", command=lambda: self._cls_remove_selected()).grid(row=2, column=0, sticky='e', padx=4, pady=(4, 0))

    def _cls_search_roots(self, text: str):
        q = (text or '').strip() or None

        def worker():
            try:
                self._start_busy('Loading classifications…')
                if q:
                    items = self.client.list_classifications(filterText=q, max_results=100, offset=0, orderBy=None, orderDirection=None)
                else:
                    items = self.client.list_root_classifications()
                for c in self.cls_tree.get_children(''):
                    self.cls_tree.delete(c)
                self.cls_tree_ids.clear()
                count = 0
                for c in items:
                    try:
                        cid = int(c.get('id'))
                        nm = str(c.get('name') or cid)
                        self.cls_name_cache[cid] = nm
                        it = self.cls_tree.insert('', tk.END, text=f"{nm} ({cid})")
                        self.cls_tree_ids[it] = cid
                        if bool(c.get('hasChildren')):
                            self.cls_tree.insert(it, tk.END, text='…')
                        count += 1
                    except Exception:
                        continue
                label = f"filter '{q}'" if q else "roots"
                self.log(f"Loaded {count} classification node(s) ({label})")
            except Exception as e:
                messagebox.showerror("Search", str(e))
                self.log("Classification search error: " + str(e))
            finally:
                self._stop_busy()

        threading.Thread(target=worker, daemon=True).start()

    def _cls_on_open(self):
        sel = self.cls_tree.selection()
        if not sel:
            return
        item = sel[0]
        self._cls_load_children_if_needed(item)

    def _cls_load_children_if_needed(self, item: str):
        cid = self.cls_tree_ids.get(item)
        if cid is None:
            return
        kids = self.cls_tree.get_children(item)
        if kids and self.cls_tree.item(kids[0], 'text') == '…':
            for k in kids:
                self.cls_tree.delete(k)

            def worker():
                try:
                    self._start_busy('Loading children…')
                    children = self.client.list_class_children(cid)
                    for ch in children:
                        try:
                            ccid = int(ch.get('id'))
                            nm = str(ch.get('name') or ccid)
                            self.cls_name_cache[ccid] = nm
                            it = self.cls_tree.insert(item, tk.END, text=f"{nm} ({ccid})")
                            self.cls_tree_ids[it] = ccid
                            if bool(ch.get('hasChildren')):
                                self.cls_tree.insert(it, tk.END, text='…')
                        except Exception:
                            pass
                except Exception as e:
                    messagebox.showerror("Children", str(e))
                    self.log("Children load error: " + str(e))
                finally:
                    self._stop_busy()

            threading.Thread(target=worker, daemon=True).start()

    def _cls_on_double(self, event):
        item = self.cls_tree.identify_row(event.y)
        if not item:
            return
        cid = self.cls_tree_ids.get(item)
        if cid is None:
            return
        parent = self.cls_tree.parent(item)
        if parent == '':
            # Top-level: recursively expand entire subtree into the tree
            self._cls_expand_full_subtree(item, cid)
        else:
            # Non-top-level: toggle open/load one level
            is_open = self.cls_tree.item(item, 'open')
            self.cls_tree.item(item, open=(not is_open))
            if not is_open:
                self._cls_load_children_if_needed(item)

    def _cls_expand_full_subtree(self, root_item: str, root_cid: int):
        def worker():
            try:
                self._start_busy('Expanding subtree…')
                stack: List[Tuple[str, int]] = [(root_item, int(root_cid))]
                calls = 0
                while stack:
                    item, cid = stack.pop()
                    try:
                        self.cls_tree.item(item, open=True)
                    except Exception:
                        pass
                    kids = self.cls_tree.get_children(item)
                    if kids and self.cls_tree.item(kids[0], 'text') == '…':
                        for k in kids:
                            self.cls_tree.delete(k)
                        try:
                            children = self.client.list_class_children(cid)
                            calls += 1
                        except Exception as e:
                            self.log(f"Children fetch error for {cid}: {e}")
                            children = []
                        for ch in children:
                            try:
                                ccid = int(ch.get('id'))
                                nm = str(ch.get('name') or ccid)
                                self.cls_name_cache[ccid] = nm
                                it = self.cls_tree.insert(item, tk.END, text=f"{nm} ({ccid})")
                                self.cls_tree_ids[it] = ccid
                                if bool(ch.get('hasChildren')):
                                    self.cls_tree.insert(it, tk.END, text='…')
                                    stack.append((it, ccid))
                            except Exception:
                                pass
                    else:
                        for k in kids:
                            subkids = self.cls_tree.get_children(k)
                            if subkids and self.cls_tree.item(subkids[0], 'text') == '…':
                                ccid = self.cls_tree_ids.get(k)
                                if isinstance(ccid, int):
                                    stack.append((k, ccid))
                    if calls > 5000:
                        self.log("Stopping subtree expand: too many child fetch calls (5000)")
                        break
                nm = self.cls_name_cache.get(root_cid) or ''
                self.log(f"Expanded subtree for {root_cid}({nm}) in the tree.")
            finally:
                self._stop_busy()

        threading.Thread(target=worker, daemon=True).start()

    def _cls_expand_selected(self):
        sel = self.cls_tree.selection()
        if not sel:
            messagebox.showinfo("Tree", "Select a classification node first.")
            return
        item = sel[0]
        self.cls_tree.item(item, open=True)
        self._cls_on_open()

    def _cls_add_selected_node(self):
        sel = self.cls_tree.selection()
        if not sel:
            messagebox.showinfo("Tree", "Select a classification node to add.")
            return
        item = sel[0]
        cid = self.cls_tree_ids.get(item)
        if cid is None:
            messagebox.showerror("Tree", "No id for selected node")
            return
        nm = self.cls_name_cache.get(cid) or ''
        self._cls_add_to_selected([cid])
        self.log(f"Added node {cid}({nm}) to selection.")

    def _cls_add_to_selected(self, ids: List[int]) -> int:
        existing: Set[int] = set()
        for it in self.cls_selected.get_children(''):
            vals = self.cls_selected.item(it, 'values')
            try:
                existing.add(int(vals[0]))
            except Exception:
                pass
        added = 0
        for cid in ids:
            if cid in existing:
                continue
            nm = self.cls_name_cache.get(cid) or ''
            self.cls_selected.insert('', tk.END, values=(cid, nm))
            added += 1
        return added

    def _cls_remove_selected(self):
        for it in self.cls_selected.selection():
            self.cls_selected.delete(it)

    def _collect_cls_selected_ids(self) -> List[int]:
        ids: List[int] = []
        for it in self.cls_selected.get_children(''):
            vals = self.cls_selected.item(it, 'values')
            try:
                cid = int(vals[0])
                ids.append(cid)
            except Exception:
                pass
        return ids
