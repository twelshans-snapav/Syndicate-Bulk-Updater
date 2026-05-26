#!/usr/bin/env python3
# main.py
# Syndicate Bulk Updater — main application window

import threading
import time
from typing import Any, Dict, List, Optional, Union

import tkinter as tk
from tkinter import ttk, messagebox

from syndicate_client import Client
from bulk_editor import BulkEditorWindow


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Syndicate Bulk Updater (Attrs + Classifications)")
        self.geometry("1360x1040")
        self.client = Client()
        self.current_folder_id: Optional[Union[int, str]] = None
        self.tree_ids: Dict[str, Union[int, str]] = {}
        self.cls_name_cache: Dict[int, str] = {}
        self._docs_offset: int = 0
        self._last_activity: float = 0.0
        self._inactivity_seconds: int = 5 * 60
        self._build_ui()
        self.bind_all('<Motion>', self._reset_inactivity_timer)
        self.bind_all('<ButtonPress>', self._reset_inactivity_timer)
        self.bind_all('<KeyPress>', self._reset_inactivity_timer)
        self._check_inactivity()

    def log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{ts}] {msg}")
        self.log_text.see(tk.END)

    # ---------- UI Shell ----------
    def _build_ui(self):
        # --- Authentication bar ---
        auth = ttk.LabelFrame(self, text="Authentication")
        auth.pack(fill=tk.X, padx=10, pady=8)
        self.domain_var = tk.StringVar(value="adiglobal")
        ttk.Label(auth, text="Domain").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        domain_entry = ttk.Entry(auth, textvariable=self.domain_var, width=14)
        domain_entry.grid(row=0, column=1, padx=5, pady=5, sticky='ew')
        domain_entry.bind('<Return>', lambda e: self.on_auth())
        ttk.Label(auth, text="Username").grid(row=0, column=2, padx=5, pady=5, sticky=tk.W)
        self.user_var = tk.StringVar()
        user_entry = ttk.Entry(auth, textvariable=self.user_var)
        user_entry.grid(row=0, column=3, padx=5, pady=5, sticky='ew')
        user_entry.bind('<Return>', lambda e: self.on_auth())
        ttk.Label(auth, text="Password").grid(row=0, column=4, padx=5, pady=5, sticky=tk.W)
        self.pw_var = tk.StringVar()
        pw_entry = ttk.Entry(auth, textvariable=self.pw_var, show='•')
        pw_entry.grid(row=0, column=5, padx=5, pady=5, sticky='ew')
        pw_entry.bind('<Return>', lambda e: self.on_auth())
        self.btn_auth = ttk.Button(auth, text="Authenticate", command=self.on_auth)
        self.btn_auth.grid(row=0, column=6, padx=8, pady=5)
        self.auth_status = tk.StringVar(value="Not authenticated")
        ttk.Label(auth, textvariable=self.auth_status, foreground="#2a72d4").grid(row=0, column=7, padx=8, sticky=tk.W)
        # Let the entry columns absorb extra space
        for col in (3, 5):
            auth.grid_columnconfigure(col, weight=1)

        # --- Busy indicator ---
        busy = ttk.Frame(self)
        self.busy_frame = busy
        self.progress = ttk.Progressbar(busy, mode='indeterminate', length=260)
        self.progress.pack(side=tk.LEFT)
        self.busy_label = ttk.Label(busy, text='')
        self.busy_label.pack(side=tk.LEFT, padx=8)
        busy.pack_forget()

        paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # --- Left pane: Folders ---
        left = ttk.Frame(paned)
        paned.add(left, weight=1)

        lf = ttk.LabelFrame(left, text="Folders")
        lf.pack(fill=tk.X, padx=5, pady=5)
        self.btn_expand = ttk.Button(lf, text="Expand Selected", command=self.on_expand_selected, state=tk.DISABLED)
        self.btn_expand.grid(row=0, column=0, padx=4, pady=4)

        tree_frame = ttk.Frame(left)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.tree = ttk.Treeview(tree_frame, show="tree")
        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        self.tree.bind("<Double-1>", self.on_tree_double)
        self.tree.bind("<<TreeviewOpen>>", self._on_tree_open)

        # --- Right pane: Documents ---
        right = ttk.Frame(paned)
        paned.add(right, weight=2)
        def _set_sash():
            paned.update()
            paned.sashpos(0, 450)
        self.after(300, _set_sash)

        rf = ttk.LabelFrame(right, text="Documents (multi-select enabled)")
        rf.pack(fill=tk.X, padx=5, pady=5)

        # Row 0: search controls
        ttk.Label(rf, text="Max:").grid(row=0, column=0, padx=4, pady=(6, 2), sticky=tk.W)
        self.max_var = tk.StringVar(value='50')
        ttk.Entry(rf, textvariable=self.max_var, width=6).grid(row=0, column=1, padx=4, pady=(6, 2), sticky='ew')
        ttk.Label(rf, text="Search:").grid(row=0, column=2, padx=(8, 4), pady=(6, 2), sticky=tk.W)
        self.search_var = tk.StringVar()
        ent = ttk.Entry(rf, textvariable=self.search_var)
        ent.grid(row=0, column=3, padx=4, pady=(6, 2), sticky='ew')
        ent.bind('<Return>', lambda e: self.reload_docs())
        ttk.Button(rf, text="Apply", command=self.reload_docs).grid(row=0, column=4, padx=4, pady=(6, 2))
        ttk.Button(rf, text="Clear", command=self.clear_search).grid(row=0, column=5, padx=4, pady=(6, 2))
        rf.grid_columnconfigure(3, weight=1)

        # Row 1: action controls
        self.btn_prev = ttk.Button(rf, text="Prev", command=self.on_prev, state=tk.DISABLED)
        self.btn_prev.grid(row=1, column=0, padx=4, pady=(2, 6), sticky='ew')
        self.btn_next = ttk.Button(rf, text="Next", command=self.on_next, state=tk.DISABLED)
        self.btn_next.grid(row=1, column=1, padx=4, pady=(2, 6), sticky='ew')
        self.btn_edit = ttk.Button(rf, text="Edit Selected…", command=self.on_edit_selected, state=tk.DISABLED)
        self.btn_edit.grid(row=1, column=2, columnspan=2, padx=4, pady=(2, 6), sticky='ew')
        self.select_all_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(rf, text="Select All", variable=self.select_all_var, command=self._on_select_all).grid(row=1, column=4, columnspan=2, padx=8, pady=(2, 6), sticky=tk.W)
        self.btn_find_replace = ttk.Button(rf, text="Find & Replace…", command=self._open_find_replace_dialog, state=tk.DISABLED)
        self.btn_find_replace.grid(row=1, column=6, padx=(4, 8), pady=(2, 6))

        # Docs treeview with both scrollbars
        docs_frame = ttk.Frame(right)
        docs_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.docs = ttk.Treeview(docs_frame, selectmode='extended', columns=("id", "name", "format", "dateUpdated", "customAttributes", "classifications"), show="headings")
        for col, w in [("id", 90), ("name", 320), ("format", 100), ("dateUpdated", 160), ("customAttributes", 420), ("classifications", 300)]:
            self.docs.heading(col, text=col)
            self.docs.column(col, width=w, minwidth=60, anchor=tk.W)
        docs_vsb = ttk.Scrollbar(docs_frame, orient=tk.VERTICAL, command=self.docs.yview)
        docs_hsb = ttk.Scrollbar(docs_frame, orient=tk.HORIZONTAL, command=self.docs.xview)
        self.docs.configure(yscrollcommand=docs_vsb.set, xscrollcommand=docs_hsb.set)
        docs_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        docs_hsb.pack(side=tk.BOTTOM, fill=tk.X)
        self.docs.pack(fill=tk.BOTH, expand=True)
        self.docs.bind('<Double-1>', self.on_doc_double_click)

        # --- Log ---
        logf = ttk.LabelFrame(self, text="Log")
        logf.pack(fill=tk.BOTH, expand=False, padx=10, pady=8)
        log_vsb = ttk.Scrollbar(logf, orient=tk.VERTICAL)
        log_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text = tk.Text(logf, height=8, wrap=tk.WORD, yscrollcommand=log_vsb.set)
        log_vsb.config(command=self.log_text.yview)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    # ---------- Busy helpers ----------
    def start_busy(self, text: str):
        try:
            self.busy_label.config(text=text)
            self.busy_frame.pack(fill=tk.X, padx=10, pady=(0, 4))
            self.progress.start(12)
            self.config(cursor='watch')
            self.update_idletasks()
        except Exception:
            pass

    def stop_busy(self):
        try:
            self.progress.stop()
            self.busy_frame.pack_forget()
            self.config(cursor='')
            self.update_idletasks()
        except Exception:
            pass

    # ---------- Inactivity sign-out ----------
    def _reset_inactivity_timer(self, event=None):
        self._last_activity = time.time()

    def _check_inactivity(self):
        if self.client.auth and self._last_activity > 0:
            if time.time() - self._last_activity >= self._inactivity_seconds:
                self._sign_out_inactivity()
                return
        self.after(30000, self._check_inactivity)

    def _sign_out_inactivity(self):
        self.client.auth = None
        self._last_activity = 0.0
        self.auth_status.set("Signed out (5 min inactivity)")
        for b in [self.btn_expand, self.btn_prev, self.btn_next, self.btn_edit, self.btn_find_replace]:
            b.config(state=tk.DISABLED)
        self.docs.delete(*self.docs.get_children())
        for c in self.tree.get_children(''):
            self.tree.delete(c)
        self.tree_ids.clear()
        self.current_folder_id = None
        self.log("Signed out due to 5 minutes of inactivity.\n")
        self.after(30000, self._check_inactivity)

    # ---------- Folder events ----------
    def on_auth(self):
        domain = (self.domain_var.get() or '').strip()
        user = (self.user_var.get() or '').strip()
        pw = self.pw_var.get()
        if not domain or not user or not pw:
            messagebox.showwarning("Missing", "Enter domain, username, and password")
            return

        def worker():
            try:
                self.btn_auth.config(state=tk.DISABLED)
                self.auth_status.set("Authenticating…")
                self.start_busy('Authenticating…')
                self.client.authenticate(domain, user, pw)
                self.auth_status.set("Authenticated")
                self._last_activity = time.time()
                for b in [self.btn_expand, self.btn_prev, self.btn_next, self.btn_edit, self.btn_find_replace]:
                    b.config(state=tk.NORMAL)
                self.on_load_tree()
            except Exception as e:
                self.auth_status.set("Auth failed")
                messagebox.showerror("Auth", str(e))
                self.log("Auth error: " + str(e))
            finally:
                self.btn_auth.config(state=tk.NORMAL)
                self.stop_busy()

        threading.Thread(target=worker, daemon=True).start()

    def on_load_tree(self):
        start = 'root'

        def worker():
            try:
                self.start_busy('Loading folders…')
                for c in self.tree.get_children(''):
                    self.tree.delete(c)
                self.tree_ids.clear()
                self.log(f"Loading subfolders of {start}…")
                subs = self.client.get_subfolders_page(start, max_results=200, offset=0)
                root_item = self.tree.insert('', tk.END, text=str(start))
                self.tree_ids[root_item] = start
                for f in subs:
                    name = str(f.get('name') or f.get('id'))
                    it = self.tree.insert(root_item, tk.END, text=name)
                    self.tree_ids[it] = f.get('id')
                    self.tree.insert(it, tk.END, text='…')
                self.tree.item(root_item, open=True)
                self.log(f"Loaded {len(subs)} subfolder(s).")
                self.current_folder_id = start
                self.reload_docs()
            except Exception as e:
                messagebox.showerror("Folders", str(e))
                self.log("Folders error: " + str(e))
            finally:
                self.stop_busy()

        threading.Thread(target=worker, daemon=True).start()

    def on_expand_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Folders", "Select a folder to expand")
            return
        item = sel[0]
        self.tree.item(item, open=True)
        self._tree_load_children_if_needed(item)

    def on_tree_select(self, event=None):
        sel = self.tree.selection()
        if not sel:
            return
        item = sel[0]
        folder_id = self.tree_ids.get(item)
        if folder_id is None:
            return
        self.current_folder_id = folder_id
        self.reload_docs()

    def on_tree_double(self, event=None):
        item = self.tree.identify_row(event.y)
        if not item:
            return
        if self.tree_ids.get(item) is None:
            return
        is_open = self.tree.item(item, 'open')
        self.tree.item(item, open=(not is_open))
        if not is_open:
            self._tree_load_children_if_needed(item)

    def _on_tree_open(self, event=None):
        item = self.tree.focus()
        if item:
            self._tree_load_children_if_needed(item)

    def _tree_load_children_if_needed(self, item: str):
        folder_id = self.tree_ids.get(item)
        if folder_id is None:
            return
        kids = self.tree.get_children(item)
        if kids and self.tree.item(kids[0], 'text') == '…':
            for k in kids:
                self.tree.delete(k)

            def worker():
                try:
                    self.start_busy('Loading subfolders…')
                    subs = self.client.get_subfolders_page(folder_id, max_results=200, offset=0)
                    for f in subs:
                        name = str(f.get('name') or f.get('id'))
                        it = self.tree.insert(item, tk.END, text=name)
                        self.tree_ids[it] = f.get('id')
                        self.tree.insert(it, tk.END, text='…')
                    self.log(f"Loaded {len(subs)} subfolder(s) for folder {folder_id}.")
                except Exception as e:
                    messagebox.showerror("Expand", str(e))
                    self.log("Expand error: " + str(e))
                finally:
                    self.stop_busy()

            threading.Thread(target=worker, daemon=True).start()

    # ---------- Docs table ----------
    def reload_docs(self, offset: int = 0):
        self._docs_offset = offset
        folder_id = self.current_folder_id or 'root'
        max_val = 50
        try:
            max_val = int(self.max_var.get())
        except Exception:
            max_val = 50
        q = (self.search_var.get() or '').strip() or None

        def worker():
            try:
                self.start_busy('Loading documents…')
                self.log(f"Listing docs for folder {folder_id} (max={max_val}, offset={offset}, filter={q})…")
                rows = self.client.get_items(folder_id, max_results=max_val, offset=offset, filterText=q)
                docs = [r for r in rows if (str(r.get('class') or '').lower() == 'document')]
                enriched = []
                for d in docs:
                    if not d.get('customAttributes') or not d.get('classifications'):
                        det = self.client.get_document(d.get('id'), include_custom=True, include_classifications=True)
                        if isinstance(det, dict):
                            if det.get('customAttributes'):
                                d['customAttributes'] = det.get('customAttributes')
                            if det.get('classifications'):
                                d['classifications'] = det.get('classifications')
                    for c in (d.get('classifications') or []):
                        try:
                            cid = int(c.get('id'))
                            nm = str(c.get('name') or '')
                            if nm:
                                self.cls_name_cache[cid] = nm
                        except Exception:
                            pass
                    enriched.append(d)
                self.select_all_var.set(False)
                self.docs.delete(*self.docs.get_children())
                for d in enriched:
                    fmt = d.get('format') or (d.get('latestVersion', {}) or {}).get('format')
                    ca = self._summarize_custom_attrs(d.get('customAttributes'))
                    cl = ", ".join([str(c.get('name') or c.get('id')) for c in (d.get('classifications') or [])])
                    self.docs.insert('', tk.END, values=(d.get('id'), d.get('name'), fmt, d.get('dateUpdated'), ca, cl))
                self.log(f"Fetched {len(enriched)} document(s) on this page.")
                # Enable/disable Prev and Next based on current position and page size
                self.btn_prev.config(state=tk.NORMAL if offset > 0 else tk.DISABLED)
                self.btn_next.config(state=tk.NORMAL if len(enriched) == max_val else tk.DISABLED)
            except Exception as e:
                messagebox.showerror("Docs", str(e))
                self.log("Docs error: " + str(e))
            finally:
                self.stop_busy()

        threading.Thread(target=worker, daemon=True).start()

    def clear_search(self):
        self.search_var.set('')
        self.reload_docs(offset=0)

    def _on_select_all(self):
        if self.select_all_var.get():
            self.docs.selection_set(self.docs.get_children())
        else:
            self.docs.selection_remove(self.docs.get_children())

    def on_prev(self):
        max_val = 50
        try:
            max_val = int(self.max_var.get())
        except Exception:
            max_val = 50
        self.reload_docs(offset=max(0, self._docs_offset - max_val))

    def on_next(self):
        max_val = 50
        try:
            max_val = int(self.max_var.get())
        except Exception:
            max_val = 50
        self.reload_docs(offset=self._docs_offset + max_val)

    def _summarize_custom_attrs(self, lst: Any, limit: int = 420) -> str:
        parts = []
        if isinstance(lst, list):
            for a in lst:
                if isinstance(a, dict):
                    n = a.get('name') or a.get('id')
                    v = a.get('value')
                    parts.append(str(n) + "=" + str(v))
        s = "; ".join(parts)
        return (s[:limit - 1] + '…') if len(s) > limit else s

    # ---------- Bulk editor ----------
    def on_edit_selected(self):
        sels = self.docs.selection()
        if not sels:
            messagebox.showinfo("Edit", "Select one or more document rows first.")
            return
        targets: List[Dict[str, Any]] = []
        for it in sels:
            vals = self.docs.item(it, 'values')
            if vals:
                targets.append({"id": vals[0], "name": vals[1]})
        if not targets:
            messagebox.showinfo("Edit", "Unable to read selected rows.")
            return

        def worker():
            try:
                self.start_busy('Loading definitions (safe)…')
                attrs = []
                try:
                    attrs = self.client.list_all_custom_attributes_safe(page_size=200)
                except Exception as e:
                    self.log("Attributes safe list failed: " + str(e))
                BulkEditorWindow(
                    self, self.client, targets, attrs,
                    cls_name_cache=self.cls_name_cache,
                    log_fn=self.log,
                    on_doc_updated=self._on_doc_updated,
                    start_busy=self.start_busy,
                    stop_busy=self.stop_busy,
                    reset_activity=self._reset_inactivity_timer,
                )
            except Exception as e:
                messagebox.showerror("Edit", str(e))
                self.log("Edit load error: " + str(e))
            finally:
                self.stop_busy()

        threading.Thread(target=worker, daemon=True).start()

    def on_doc_double_click(self, event):
        item = self.docs.identify_row(event.y)
        if not item:
            return
        vals = self.docs.item(item, 'values')
        if not vals:
            return
        doc_id, current_name = vals[0], vals[1]
        self._open_rename_dialog(doc_id, current_name, item)

    def _open_rename_dialog(self, doc_id: Any, current_name: str, tree_item: str):
        win = tk.Toplevel(self)
        win.title(f"Rename Document")
        win.geometry("520x140")
        win.resizable(True, False)
        win.grab_set()

        frm = ttk.Frame(win)
        frm.pack(fill=tk.BOTH, expand=True, padx=16, pady=14)
        frm.columnconfigure(1, weight=1)

        ttk.Label(frm, text="Document ID:").grid(row=0, column=0, sticky='w', pady=(0, 6))
        ttk.Label(frm, text=str(doc_id), foreground="#888").grid(row=0, column=1, sticky='w', padx=8, pady=(0, 6))

        ttk.Label(frm, text="Name:").grid(row=1, column=0, sticky='w')
        name_var = tk.StringVar(value=current_name)
        name_entry = ttk.Entry(frm, textvariable=name_var)
        name_entry.grid(row=1, column=1, sticky='ew', padx=8)
        name_entry.select_range(0, tk.END)
        name_entry.focus()

        btn_frame = ttk.Frame(frm)
        btn_frame.grid(row=2, column=0, columnspan=2, sticky='e', pady=(14, 0))

        def on_apply():
            new_name = name_var.get().strip()
            if not new_name:
                messagebox.showwarning("Rename", "Name cannot be empty.", parent=win)
                return
            if new_name == current_name:
                win.destroy()
                return

            def worker():
                try:
                    self.start_busy(f"Renaming document {doc_id}…")
                    result = self.client.update_document(doc_id, new_name)
                    updated_name = result.get('name', new_name)
                    vals = list(self.docs.item(tree_item, 'values'))
                    vals[1] = updated_name
                    self.docs.item(tree_item, values=vals)
                    self.log(f"Renamed doc {doc_id}: '{current_name}' → '{updated_name}'")
                    win.destroy()
                except Exception as e:
                    messagebox.showerror("Rename Failed", str(e), parent=win)
                    self.log(f"Rename error (doc {doc_id}): {e}")
                finally:
                    self.stop_busy()

            threading.Thread(target=worker, daemon=True).start()

        name_entry.bind('<Return>', lambda e: on_apply())
        ttk.Button(btn_frame, text="Cancel", command=win.destroy).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_frame, text="Apply", command=on_apply).pack(side=tk.LEFT)

    def _on_doc_updated(self, doc_id: Any, after: Dict[str, Any]):
        for item in self.docs.get_children(''):
            v = self.docs.item(item, 'values')
            if v and str(v[0]) == str(doc_id):
                fmt = after.get('format') or (after.get('latestVersion', {}) or {}).get('format')
                ca = self._summarize_custom_attrs(after.get('customAttributes'))
                cl = ", ".join([str(c.get('name') or c.get('id')) for c in (after.get('classifications') or [])])
                self.docs.item(item, values=(after.get('id'), after.get('name'), fmt, after.get('dateUpdated'), ca, cl))
                break


    def _open_find_replace_dialog(self):
        current_docs = []
        for it in self.docs.get_children():
            vals = self.docs.item(it, 'values')
            if vals:
                current_docs.append({"id": vals[0], "name": vals[1], "_item": it})
        if not current_docs:
            messagebox.showinfo("Find & Replace", "No documents loaded. Navigate to a folder first.")
            return

        win = tk.Toplevel(self)
        win.title("Find & Replace — Document Names")
        win.geometry("820x540")
        win.grab_set()
        win.rowconfigure(2, weight=1)
        win.columnconfigure(0, weight=1)

        # Inputs row
        top = ttk.Frame(win)
        top.grid(row=0, column=0, sticky='ew', padx=12, pady=(12, 4))
        top.columnconfigure(1, weight=1)
        top.columnconfigure(3, weight=1)
        ttk.Label(top, text="Find:").grid(row=0, column=0, sticky='w', padx=(0, 4))
        find_var = tk.StringVar()
        ttk.Entry(top, textvariable=find_var).grid(row=0, column=1, sticky='ew', padx=(0, 12))
        ttk.Label(top, text="Replace with:").grid(row=0, column=2, sticky='w', padx=(0, 4))
        replace_var = tk.StringVar()
        ttk.Entry(top, textvariable=replace_var).grid(row=0, column=3, sticky='ew', padx=(0, 8))
        ttk.Button(top, text="Preview", command=lambda: on_preview()).grid(row=0, column=4, padx=(4, 0))

        ttk.Label(win, text="Preview — documents whose names contain the find text:").grid(
            row=1, column=0, sticky='w', padx=12, pady=(8, 2))

        # Preview treeview
        pf = ttk.Frame(win)
        pf.grid(row=2, column=0, sticky='nsew', padx=12, pady=4)
        pf.rowconfigure(0, weight=1)
        pf.columnconfigure(0, weight=1)
        preview = ttk.Treeview(pf, columns=("id", "old_name", "new_name"), show='headings')
        for col, w, label in [("id", 90, "ID"), ("old_name", 330, "Old Name"), ("new_name", 330, "New Name")]:
            preview.heading(col, text=label)
            preview.column(col, width=w, minwidth=60, anchor=tk.W)
        vsb = ttk.Scrollbar(pf, orient=tk.VERTICAL, command=preview.yview)
        hsb = ttk.Scrollbar(pf, orient=tk.HORIZONTAL, command=preview.xview)
        preview.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.grid(row=0, column=1, sticky='ns')
        hsb.grid(row=1, column=0, sticky='ew')
        preview.grid(row=0, column=0, sticky='nsew')

        # Bottom bar
        bottom = ttk.Frame(win)
        bottom.grid(row=3, column=0, sticky='ew', padx=12, pady=(4, 10))
        bottom.columnconfigure(1, weight=1)
        prog = ttk.Progressbar(bottom, mode='determinate', maximum=1)
        prog.grid(row=0, column=0, sticky='ew', padx=(0, 8))
        prog_lbl = ttk.Label(bottom, text="")
        prog_lbl.grid(row=0, column=1, sticky='w')
        ttk.Button(bottom, text="Cancel", command=win.destroy).grid(row=0, column=2, padx=(0, 4))
        apply_btn = ttk.Button(bottom, text="Apply 0 rename(s)", state=tk.DISABLED)
        apply_btn.grid(row=0, column=3)

        _matches: List[Dict[str, Any]] = []

        def on_preview():
            find = find_var.get()
            if not find:
                messagebox.showinfo("Preview", "Enter a find string first.", parent=win)
                return
            replace = replace_var.get()
            matches = [d for d in current_docs if find in d['name']]
            preview.delete(*preview.get_children())
            _matches.clear()
            for d in matches:
                new_name = d['name'].replace(find, replace)
                preview.insert('', tk.END, values=(d['id'], d['name'], new_name))
                _matches.append({**d, 'new_name': new_name})
            count = len(_matches)
            prog['maximum'] = max(1, count)
            prog['value'] = 0
            apply_btn.config(
                text=f"Apply {count} rename(s)",
                state=tk.NORMAL if count > 0 else tk.DISABLED,
            )
            prog_lbl.config(text=f"{count} match(es) found")

        def on_apply():
            if not _matches:
                return
            apply_btn.config(state=tk.DISABLED)
            total = len(_matches)
            prog['maximum'] = total
            prog['value'] = 0

            def worker():
                done = 0
                succeeded = 0
                errors: List[str] = []
                for m in _matches:
                    prog_lbl.config(text=f"Renaming {done + 1}/{total}…")
                    prog['value'] = done
                    win.update_idletasks()
                    try:
                        result = self.client.update_document(m['id'], m['new_name'])
                        updated_name = result.get('name', m['new_name'])
                        try:
                            vals = list(self.docs.item(m['_item'], 'values'))
                            vals[1] = updated_name
                            self.docs.item(m['_item'], values=vals)
                        except Exception:
                            pass
                        self.log(f"Renamed doc {m['id']}: '{m['name']}' → '{updated_name}'")
                        succeeded += 1
                        self._reset_inactivity_timer()
                    except Exception as e:
                        errors.append(f"• {m['name']} (id {m['id']}): {e}")
                        self.log(f"Rename error (doc {m['id']}): {e}")
                    finally:
                        done += 1
                        prog['value'] = done
                        win.update_idletasks()

                prog_lbl.config(text="Done")
                summary = f"Find & Replace complete.\n\nSucceeded: {succeeded}/{total}"
                if errors:
                    summary += f"\nFailed: {len(errors)}\n\n" + "\n".join(errors)
                messagebox.showinfo("Find & Replace", summary, parent=win)
                win.destroy()

            threading.Thread(target=worker, daemon=True).start()

        apply_btn.config(command=on_apply)
        find_var.trace_add('write', lambda *_: apply_btn.config(state=tk.DISABLED, text="Apply 0 rename(s)"))
        replace_var.trace_add('write', lambda *_: apply_btn.config(state=tk.DISABLED, text="Apply 0 rename(s)"))
        win.bind('<Return>', lambda e: on_preview())


if __name__ == '__main__':
    app = App()
    app.mainloop()
