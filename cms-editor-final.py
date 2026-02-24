
#!/usr/bin/env python3
# cms_gui_version_attrs_bulk_cls_tree_SUBTREE_full.py
# Syndicate — BULK updater (Folders + Docs + Attributes + Classifications tab modeled after working backup)

import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union, Set, Tuple

try:
    import requests
except Exception:
    requests = None
import tkinter as tk
from tkinter import ttk, messagebox

@dataclass
class Auth:
    domain: str
    header_name: str
    token: str

class Client:
    def __init__(self):
        self.auth: Optional[Auth] = None
        self.session = requests.Session() if requests else None
        self.timeout = 30

    def _require(self):
        if not requests:
            raise RuntimeError("Install requests: pip install requests")
        if not self.session:
            raise RuntimeError("requests session not available")

    def base(self, domain: str) -> str:
        return "https://core-" + domain + ".bravais.com/api/v3"

    def authenticate(self, domain: str, username: str, password: str) -> Auth:
        self._require()
        url = self.base(domain) + "/authenticate/"
        r = self.session.post(url, json={"username": username, "password": password}, timeout=self.timeout)
        if r.status_code >= 400:
            raise RuntimeError(f"Auth failed ({r.status_code}): {r.text or ''}")
        data = r.json()
        name, token = None, None
        if isinstance(data, dict):
            if ('name' in data) and ('value' in data):
                name, token = data.get('name'), data.get('value')
            elif ('context' in data) and ('token' in data):
                name, token = data.get('context'), data.get('token')
            elif 'headers' in data and isinstance(data['headers'], list) and data['headers']:
                name, token = data['headers'][0].get('name'), data['headers'][0].get('value')
            else:
                for k, v in data.items():
                    if isinstance(v, str) and k.lower().startswith('bravais-') and k.lower().endswith('-context'):
                        name, token = k, v
                        break
        if not name or not token:
            raise RuntimeError("Could not parse auth response for context header/token")
        self.auth = Auth(domain=domain, header_name=name, token=token)
        return self.auth

    def _h(self) -> Dict[str, str]:
        if not self.auth:
            raise RuntimeError("Not authenticated")
        return { self.auth.header_name: self.auth.token, 'Accept': 'application/json' }

    # ---------- Docs & Folders ----------
    def get_document(self, doc_id: Union[int,str], include_custom: bool=True, include_classifications: bool=True) -> Dict[str,Any]:
        self._require()
        url = self.base(self.auth.domain) + f"/documents/{doc_id}"
        params = []
        if include_custom:
            params.append(("includeCustomAttributes", "true"))
        if include_classifications:
            params.append(("includeClassifications", "true"))
        r = self.session.get(url, headers=self._h(), params=params or None, timeout=self.timeout)
        if r.status_code >= 400:
            raise RuntimeError(f"Document fetch failed ({r.status_code}): {r.text or ''}")
        return r.json()

    def get_items(self, folder_id: Union[int,str], *, max_results: int=50, offset: int=0, filterText: Optional[str]=None) -> List[Dict[str,Any]]:
        self._require()
        url = self.base(self.auth.domain) + f"/folders/{folder_id}/items"
        params: Dict[str,Any] = {"max": max_results, "offset": offset, "includeCustomAttributes":"true", "includeClassifications":"true"}
        if filterText:
            params['filterText'] = filterText
        r = self.session.get(url, headers=self._h(), params=params, timeout=self.timeout)
        if r.status_code >= 400:
            raise RuntimeError(f"Items failed ({r.status_code}): {r.text or ''}")
        data = r.json()
        return data if isinstance(data, list) else (data.get('items', []) if isinstance(data, dict) else [])

    def get_subfolders_page(self, folder_id: Union[int,str], *, max_results: int=200, offset: int=0) -> List[Dict[str,Any]]:
        self._require()
        url = self.base(self.auth.domain) + f"/folders/{folder_id}/subfolders"
        params = {"max": max_results, "offset": offset, "folderPath": "true"}
        r = self.session.get(url, headers=self._h(), params=params, timeout=self.timeout)
        if r.status_code >= 400:
            raise RuntimeError(f"Subfolders failed ({r.status_code}): {r.text or ''}")
        data = r.json()
        return data if isinstance(data, list) else (data.get('items', []) if isinstance(data, dict) else [])

    def get_subfolders_all(self, folder_id: Union[int,str], *, page_size: int=200) -> List[Dict[str,Any]]:
        results: List[Dict[str,Any]] = []
        offset = 0
        while True:
            page = self.get_subfolders_page(folder_id, max_results=page_size, offset=offset)
            if not page:
                break
            results.extend(page)
            offset += len(page)
            if offset > 20000:
                break
        return results

    # ---------- Custom Attributes ----------
    def list_custom_attributes(self, *, filterText: Optional[str]=None, max_results: int=200, offset: int=0,
                               orderBy: Optional[str]='name', orderDirection: Optional[str]='asc') -> List[Dict[str,Any]]:
        self._require()
        url = self.base(self.auth.domain) + "/customAttributes"
        params: Dict[str,Any] = {}
        if filterText: params['filterText'] = filterText
        if max_results: params['max'] = max_results
        if offset: params['offset'] = offset
        if orderBy: params['orderBy'] = orderBy
        if orderDirection: params['orderDirection'] = orderDirection
        r = self.session.get(url, headers=self._h(), params=params, timeout=self.timeout)
        if r.status_code >= 400:
            raise RuntimeError(f"Custom attributes list failed ({r.status_code}): {r.text or ''}")
        data = r.json()
        return data if isinstance(data, list) else (data.get('items', []) if isinstance(data, dict) else [])

    def list_all_custom_attributes_safe(self, *, page_size: int=200) -> List[Dict[str,Any]]:
        out: Dict[int, Dict[str,Any]] = {}
        offset = 0
        while True:
            try:
                page = self.list_custom_attributes(max_results=page_size, offset=offset, orderBy='name', orderDirection='asc')
            except Exception:
                page = None
            if page is None:
                break
            if not page:
                return list(out.values())
            for a in page:
                try:
                    aid = int(a.get('id'))
                    if aid not in out:
                        out[aid] = a
                except Exception:
                    pass
            offset += len(page)
            if offset > 20000:
                break
        offset = 0
        while True:
            try:
                page = self.list_custom_attributes(max_results=page_size, offset=offset, orderBy=None, orderDirection=None)
            except Exception:
                break
            if not page:
                break
            for a in page:
                try:
                    aid = int(a.get('id'))
                    if aid not in out:
                        out[aid] = a
                except Exception:
                    pass
            offset += len(page)
            if offset > 20000:
                break
        return list(out.values())

    def post_version_attr(self, version_id: Union[int,str], attr_id: int, value: str) -> Dict[str,Any]:
        self._require()
        url = self.base(self.auth.domain) + f"/documentVersions/{version_id}/customAttributes/{attr_id}"
        headers = { **self._h(), 'Content-Type': 'application/json' }
        r = self.session.post(url, headers=headers, params={"value": value}, timeout=self.timeout)
        if r.status_code >= 400:
            raise RuntimeError(f"Update failed ({r.status_code}): {r.text or ''}")
        try:
            return r.json() if r.content else {}
        except Exception:
            return {"raw": r.text or ''}

    # ---------- Classifications ----------
    def list_classifications(self, *, filterText: Optional[str]=None, max_results: int=200, offset: int=0,
                             orderBy: Optional[str]='name', orderDirection: Optional[str]='asc') -> List[Dict[str,Any]]:
        self._require()
        url = self.base(self.auth.domain) + "/classifications"
        params: Dict[str,Any] = {}
        if filterText: params['filterText'] = filterText
        if max_results: params['max'] = max_results
        if offset: params['offset'] = offset
        if orderBy: params['orderBy'] = orderBy
        if orderDirection: params['orderDirection'] = orderDirection
        r = self.session.get(url, headers=self._h(), params=params, timeout=self.timeout)
        if r.status_code >= 400:
            raise RuntimeError(f"Classifications list failed ({r.status_code}): {r.text or ''}")
        data = r.json()
        return data if isinstance(data, list) else (data.get('items', []) if isinstance(data, dict) else [])

    def list_class_children(self, classification_id: Union[int,str]) -> List[Dict[str,Any]]:
        self._require()
        url = self.base(self.auth.domain) + f"/classifications/{classification_id}/children"
        r = self.session.get(url, headers=self._h(), timeout=self.timeout)
        if r.status_code == 404:
            return []
        if r.status_code >= 400:
            raise RuntimeError(f"Class children failed ({r.status_code}): {r.text or ''}")
        data = r.json()
        return data if isinstance(data, list) else (data.get('items', []) if isinstance(data, dict) else [])

    def set_document_classifications(self, doc_id: Union[int,str], class_ids: List[int], *, replace_all: bool=True) -> Dict[str,Any]:
        self._require()
        url = self.base(self.auth.domain) + f"/documents/{doc_id}/classifications"
        headers = { **self._h(), 'Content-Type': 'application/json' }
        params = { 'replaceAll': 'true' if replace_all else 'false' }
        r = self.session.post(url, headers=headers, params=params, json=(class_ids or []), timeout=self.timeout)
        if r.status_code >= 400:
            raise RuntimeError(f"Set classifications failed ({r.status_code}): {r.text or ''}")
        try:
            return r.json() if r.content else {}
        except Exception:
            return {"raw": r.text or ''}

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Syndicate Bulk Updater (Attrs + Classifications)")
        self.geometry("1360x1040")
        self.client = Client()
        self.current_folder_id: Optional[Union[int,str]] = None
        self.tree_ids: Dict[str, Union[int,str]] = {}
        self.cls_name_cache: Dict[int, str] = {}
        self._build_ui()

    def log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{ts}] {msg}")
        self.log_text.see(tk.END)

    # ---------- UI Shell ----------
    def _build_ui(self):
        auth = ttk.LabelFrame(self, text="Authentication")
        auth.pack(fill=tk.X, padx=10, pady=8)
        ttk.Label(auth, text="Domain").grid(row=0, column=0, padx=5, pady=5)
        self.domain_var = tk.StringVar(value="adiglobal")
        ttk.Entry(auth, textvariable=self.domain_var, width=20).grid(row=0, column=1, padx=5, pady=5)
        ttk.Label(auth, text="Username").grid(row=0, column=2, padx=5, pady=5)
        self.user_var = tk.StringVar()
        ttk.Entry(auth, textvariable=self.user_var, width=28).grid(row=0, column=3, padx=5, pady=5)
        ttk.Label(auth, text="Password").grid(row=0, column=4, padx=5, pady=5)
        self.pw_var = tk.StringVar()
        ttk.Entry(auth, textvariable=self.pw_var, width=28, show='•').grid(row=0, column=5, padx=5, pady=5)
        self.btn_auth = ttk.Button(auth, text="Authenticate", command=self.on_auth)
        self.btn_auth.grid(row=0, column=6, padx=8, pady=5)
        self.auth_status = tk.StringVar(value="Not authenticated")
        ttk.Label(auth, textvariable=self.auth_status, foreground="#2a72d4").grid(row=0, column=7, padx=8)
        auth.grid_columnconfigure(7, weight=1)

        busy = ttk.Frame(self)
        self.busy_frame = busy
        self.progress = ttk.Progressbar(busy, mode='indeterminate', length=260)
        self.progress.pack(side=tk.LEFT)
        self.busy_label = ttk.Label(busy, text='')
        self.busy_label.pack(side=tk.LEFT, padx=8)
        busy.pack_forget()

        paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        left = ttk.Frame(paned)
        paned.add(left, weight=1)
        lf = ttk.LabelFrame(left, text="Folders")
        lf.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(lf, text="Start").grid(row=0, column=0, padx=4, pady=4)
        self.start_folder_var = tk.StringVar(value='root')
        ttk.Entry(lf, textvariable=self.start_folder_var, width=16).grid(row=0, column=1, padx=4, pady=4)
        self.btn_load_tree = ttk.Button(lf, text="Load Subfolders", command=self.on_load_tree, state=tk.DISABLED)
        self.btn_load_tree.grid(row=0, column=2, padx=4, pady=4)
        self.btn_expand = ttk.Button(lf, text="Expand Selected", command=self.on_expand_selected, state=tk.DISABLED)
        self.btn_expand.grid(row=0, column=3, padx=4, pady=4)

        self.tree = ttk.Treeview(left, show="tree", height=22)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        self.tree.bind("<Double-1>", self.on_tree_double)

        right = ttk.Frame(paned)
        paned.add(right, weight=2)
        rf = ttk.LabelFrame(right, text="Documents (multi-select enabled)")
        rf.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(rf, text="Max:").grid(row=0, column=0, padx=4)
        self.max_var = tk.StringVar(value='50')
        ttk.Entry(rf, textvariable=self.max_var, width=8).grid(row=0, column=1, padx=4)
        ttk.Label(rf, text="Search:").grid(row=0, column=2, padx=8)
        self.search_var = tk.StringVar()
        ent = ttk.Entry(rf, textvariable=self.search_var, width=26)
        ent.grid(row=0, column=3, padx=4)
        ent.bind('<Return>', lambda e: self.reload_docs())
        ttk.Button(rf, text="Apply", command=self.reload_docs).grid(row=0, column=4, padx=4)
        ttk.Button(rf, text="Clear", command=self.clear_search).grid(row=0, column=5, padx=4)
        self.btn_prev = ttk.Button(rf, text="Prev", command=self.on_prev, state=tk.DISABLED)
        self.btn_prev.grid(row=0, column=6, padx=4)
        self.btn_next = ttk.Button(rf, text="Next", command=self.on_next, state=tk.DISABLED)
        self.btn_next.grid(row=0, column=7, padx=4)
        self.btn_edit = ttk.Button(rf, text="Edit Selected…", command=self.on_edit_selected, state=tk.DISABLED)
        self.btn_edit.grid(row=0, column=8, padx=6)

        docs_frame = ttk.Frame(right)
        docs_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.docs = ttk.Treeview(docs_frame, selectmode='extended', columns=("id","name","format","dateUpdated","customAttributes","classifications"), show="headings", height=22)
        for col, w in [("id",90),("name",320),("format",100),("dateUpdated",160),("customAttributes",420),("classifications",300)]:
            self.docs.heading(col, text=col)
            self.docs.column(col, width=w, anchor=tk.W)
        self.docs.pack(fill=tk.BOTH, expand=True)

        logf = ttk.LabelFrame(self, text="Log")
        logf.pack(fill=tk.BOTH, expand=False, padx=10, pady=8)
        self.log_text = tk.Text(logf, height=10, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    # ---------- Busy helpers ----------
    def start_busy(self, text: str):
        try:
            self.busy_label.config(text=text)
            self.busy_frame.pack(fill=tk.X, padx=10, pady=(0,4))
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

    # ---------- Folders events ----------
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
                for b in [self.btn_load_tree, self.btn_expand, self.btn_prev, self.btn_next, self.btn_edit]:
                    b.config(state=tk.NORMAL)
                self.start_folder_var.set('root')
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
        start = (self.start_folder_var.get() or 'root').strip()
        def worker():
            try:
                self.start_busy('Loading folders…')
                for c in self.tree.get_children(''):
                    self.tree.delete(c)
                self.tree_ids.clear()
                self.log(f"Loading first-level subfolders of {start}…")
                subs = self.client.get_subfolders_all(start, page_size=200)
                root_item = self.tree.insert('', tk.END, text=str(start))
                self.tree_ids[root_item] = start
                for f in subs:
                    name = str(f.get('name') or f.get('id'))
                    it = self.tree.insert(root_item, tk.END, text=name)
                    self.tree_ids[it] = f.get('id')
                self.tree.item(root_item, open=True)
                self.log(f"Loaded {len(subs)} subfolder(s). Double-click to expand.")
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
        folder_id = self.tree_ids.get(item)
        self._toggle_expand(item, folder_id)

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
        folder_id = self.tree_ids.get(item)
        if folder_id is None:
            return
        self._toggle_expand(item, folder_id)

    def _toggle_expand(self, item, folder_id: Union[int,str]):
        def worker():
            try:
                self.start_busy('Loading subfolders…')
                is_open = self.tree.item(item, 'open')
                if is_open:
                    self.tree.item(item, open=False)
                else:
                    for c in self.tree.get_children(item):
                        self.tree.delete(c)
                    subs = self.client.get_subfolders_all(folder_id, page_size=200)
                    for f in subs:
                        name = str(f.get('name') or f.get('id'))
                        it = self.tree.insert(item, tk.END, text=name)
                        self.tree_ids[it] = f.get('id')
                    self.tree.item(item, open=True)
                self.current_folder_id = folder_id
                self.reload_docs()
            except Exception as e:
                messagebox.showerror("Expand", str(e))
                self.log("Expand error: " + str(e))
            finally:
                self.stop_busy()
        threading.Thread(target=worker, daemon=True).start()

    # ---------- Docs table ----------
    def reload_docs(self):
        folder_id = self.current_folder_id or (self.start_folder_var.get() or 'root')
        max_val = 50
        try:
            max_val = int(self.max_var.get())
        except Exception:
            max_val = 50
        q = (self.search_var.get() or '').strip() or None
        def worker():
            try:
                self.start_busy('Loading documents…')
                self.log(f"Listing docs for folder {folder_id} (max={max_val}, filter={q})…")
                rows = self.client.get_items(folder_id, max_results=max_val, offset=0, filterText=q)
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
                self.docs.delete(*self.docs.get_children())
                for d in enriched:
                    fmt = d.get('format') or (d.get('latestVersion', {}) or {}).get('format')
                    ca = self._summarize_custom_attrs(d.get('customAttributes'))
                    cl = ", ".join([str(c.get('name') or c.get('id')) for c in (d.get('classifications') or [])])
                    self.docs.insert('', tk.END, values=(d.get('id'), d.get('name'), fmt, d.get('dateUpdated'), ca, cl))
                self.log(f"Fetched {len(enriched)} document(s) on this page.")
            except Exception as e:
                messagebox.showerror("Docs", str(e))
                self.log("Docs error: " + str(e))
            finally:
                self.stop_busy()
        threading.Thread(target=worker, daemon=True).start()

    def clear_search(self):
        self.search_var.set('')
        self.reload_docs()

    def on_prev(self):
        pass
    def on_next(self):
        pass

    def _summarize_custom_attrs(self, lst: Any, limit: int=420) -> str:
        parts = []
        if isinstance(lst, list):
            for a in lst:
                if isinstance(a, dict):
                    n = a.get('name') or a.get('id')
                    v = a.get('value')
                    parts.append(str(n) + "=" + str(v))
        s = "; ".join(parts)
        return (s[:limit-1] + '…') if len(s) > limit else s

    # ---------- Bulk editor ----------
    def on_edit_selected(self):
        sels = self.docs.selection()
        if not sels:
            messagebox.showinfo("Edit", "Select one or more document rows first.")
            return
        targets: List[Dict[str,Any]] = []
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
                self._open_bulk_editor(targets, attrs)
            except Exception as e:
                messagebox.showerror("Edit", str(e))
                self.log("Edit load error: " + str(e))
            finally:
                self.stop_busy()
        threading.Thread(target=worker, daemon=True).start()

    def _open_bulk_editor(self, targets: List[Dict[str,Any]], defs_attrs: List[Dict[str,Any]]):
        count = len(targets)
        win = tk.Toplevel(self)
        win.title("Bulk Edit — " + str(count) + " document(s)")
        win.geometry("1360x880")

        paned = ttk.PanedWindow(win, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(paned)
        paned.add(left, weight=1)
        ttk.Label(left, text="Target documents").pack(anchor='w', padx=8, pady=(8,2))
        tgt_cols = ("id","name")
        tgt = ttk.Treeview(left, columns=tgt_cols, show='headings', height=24)
        for c,w in [("id",100),("name",360)]:
            tgt.heading(c, text=c)
            tgt.column(c, width=w, anchor=tk.W)
        tgt.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        for t in targets:
            tgt.insert('', tk.END, values=(t['id'], t['name']))

        right = ttk.Notebook(paned)
        paned.add(right, weight=2)

        # Attributes tab
        tab_attr = ttk.Frame(right)
        right.add(tab_attr, text='Custom Attributes')
        self._build_attr_tab(tab_attr, defs_attrs)

        # Classifications tree tab (modeled after working backup)
        tab_cls = ttk.Frame(right)
        right.add(tab_cls, text='Classifications (Tree)')
        self._build_cls_tree_tab(tab_cls)

        bottom = ttk.Frame(win)
        bottom.pack(fill=tk.X, padx=10, pady=(4,10))
        self.cls_replace_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(bottom, text='Replace ALL existing classifications (unchecked = merge/add)', variable=self.cls_replace_var).pack(side=tk.LEFT, padx=(4,12))
        prog = ttk.Progressbar(bottom, mode='determinate', maximum=max(1, len(targets)))
        prog.pack(side=tk.LEFT, padx=(4,10))
        prog_lbl = ttk.Label(bottom, text="Ready")
        prog_lbl.pack(side=tk.LEFT)

        dry_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(bottom, text='Dry run (log only)', variable=dry_var).pack(side=tk.LEFT, padx=(12,0))

        def on_apply():
            edits_attrs = self._collect_attr_edits()
            sel_cls_ids = self._collect_cls_selected_ids()
            replace_all = bool(self.cls_replace_var.get())
            if not edits_attrs and not sel_cls_ids:
                messagebox.showinfo("No changes", "Add at least one attribute or classification change.")
                return
            is_dry = bool(dry_var.get())

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
                    for t in targets:
                        did = t['id']
                        prog_lbl.config(text=("Dry-run " if is_dry else "Updating ") + f"doc {did} (" + str(done+1) + f"/{total})…")
                        prog['value'] = done
                        win.update_idletasks()
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
                            if is_dry:
                                for e in edits_attrs:
                                    self.log(f"DRY-RUN doc {did} — Attr {e['id']}: WOULD SET={e['value']}")
                            else:
                                for e in edits_attrs:
                                    self.log(f"POST version attr: ver={ver} attr={e['id']} value={e['value']}")
                                    self.client.post_version_attr(ver, e['id'], e['value'])
                            # Classifications
                            if sel_cls_ids:
                                target_ids = sel_cls_ids if replace_all else sorted(set(b_cls_ids) | set(sel_cls_ids))
                                if is_dry:
                                    self.log("DRY-RUN doc " + str(did) + " — Classifications: CURRENT=[" + ", ".join(names_for_ids(b_cls_ids)) + "] -> WOULD SET=[" + ", ".join(names_for_ids(target_ids)) + "] " + ("(replace)" if replace_all else "(merge)"))
                                else:
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
                            # Update main grid row
                            for item in self.docs.get_children(''):
                                v = self.docs.item(item, 'values')
                                if v and str(v[0]) == str(did):
                                    fmt = after.get('format') or (after.get('latestVersion', {}) or {}).get('format')
                                    ca = self._summarize_custom_attrs(after.get('customAttributes'))
                                    cl = ", ".join([str(c.get('name') or c.get('id')) for c in (after.get('classifications') or [])])
                                    self.docs.item(item, values=(after.get('id'), after.get('name'), fmt, after.get('dateUpdated'), ca, cl))
                                    break
                        except Exception as e:
                            messagebox.showerror("Update", "Doc " + str(did) + ": " + str(e))
                            self.log("Update error (doc " + str(did) + "): " + str(e))
                        finally:
                            done += 1
                            prog['value'] = done
                            win.update_idletasks()
                    prog_lbl.config(text="Dry-run complete" if is_dry else "Done")
                    messagebox.showinfo("Bulk Edit", ("Dry-run complete. No changes were made." if is_dry else "Applied changes to ") + str(done) + (" document(s)." if not is_dry else " document(s) evaluated."))
                    win.destroy()
                except Exception as e:
                    messagebox.showerror("Bulk Edit", str(e))
                    self.log("Bulk update error: " + str(e))
            threading.Thread(target=worker, daemon=True).start()

        ttk.Button(bottom, text="Apply to " + str(count) + " document(s)", command=on_apply).pack(side=tk.RIGHT, padx=6)
        ttk.Button(bottom, text="Cancel", command=win.destroy).pack(side=tk.RIGHT)

    # ---------- Attributes tab ----------
    def _build_attr_tab(self, parent: tk.Widget, defs: List[Dict[str,Any]]):
        frm = ttk.Frame(parent)
        frm.pack(fill=tk.BOTH, expand=True)
        def_by_id: Dict[int, Dict[str,Any]] = {}
        id_by_name: Dict[str,int] = {}
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

        ttk.Label(frm, text="Attribute Name").grid(row=0, column=0, sticky=tk.W, padx=8, pady=(8,4))
        name_var = tk.StringVar()
        name_combo = ttk.Combobox(frm, textvariable=name_var, values=names_sorted, state='readonly', width=42)
        name_combo.grid(row=0, column=1, sticky=tk.W)

        ttk.Label(frm, text="Filter").grid(row=0, column=2, sticky=tk.W, padx=(12,4))
        filt_var = tk.StringVar()
        ttk.Entry(frm, textvariable=filt_var, width=24).grid(row=0, column=3, sticky=tk.W)
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
        ttk.Button(frm, text="Load Names", command=on_fetch_names).grid(row=0, column=4, sticky=tk.W, padx=6)

        ttk.Label(frm, text="Value").grid(row=1, column=0, sticky=tk.W, padx=8)
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
                cb = ttk.Combobox(frm, textvariable=v, values=[''] + vals, state='readonly', width=40)
                cb.grid(row=1, column=1, sticky=tk.W)
                dyn_val_var, dyn_widget = v, cb
            elif t == 'boolean':
                v = tk.StringVar()
                cb = ttk.Combobox(frm, textvariable=v, values=['','Yes','No','True','False','1','0'], state='readonly', width=20)
                cb.grid(row=1, column=1, sticky=tk.W)
                dyn_val_var, dyn_widget = v, cb
            else:
                v = tk.StringVar()
                ent = ttk.Entry(frm, textvariable=v, width=46)
                ent.grid(row=1, column=1, sticky=tk.W)
                dyn_val_var, dyn_widget = v, ent
        name_combo.bind('<<ComboboxSelected>>', on_attr_selected)

        ttk.Button(frm, text="Add Attribute Change", command=lambda: add_attr_change()).grid(row=1, column=4, sticky=tk.E, padx=8)

        ttk.Label(frm, text="Pending attribute changes").grid(row=2, column=0, columnspan=5, sticky=tk.W, padx=8, pady=(8,2))
        cols = ("id","name","value")
        self.attr_changes = ttk.Treeview(frm, columns=cols, show='headings', height=10)
        for c,w in [("id",80),("name",260),("value",360)]:
            self.attr_changes.heading(c, text=c)
            self.attr_changes.column(c, width=w, anchor=tk.W)
        self.attr_changes.grid(row=3, column=0, columnspan=5, sticky='nsew', padx=8, pady=6)
        frm.grid_rowconfigure(3, weight=1)
        ttk.Button(frm, text="Remove Selected", command=lambda: remove_rows(self.attr_changes)).grid(row=4, column=4, sticky=tk.E, padx=8, pady=(0,8))

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

    def _collect_attr_edits(self) -> List[Dict[str,Any]]:
        edits: List[Dict[str,Any]] = []
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

    # ---------- Classifications TREE tab (Search Roots / Expand / Add Node / Add Subtree) ----------
    def _build_cls_tree_tab(self, parent: tk.Widget):
        frm = ttk.Frame(parent)
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frm, text="Find classifications (filter)").grid(row=0, column=0, sticky=tk.W, padx=8, pady=(8,4))
        self.cls_filter_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.cls_filter_var, width=36).grid(row=0, column=1, sticky=tk.W)
        ttk.Button(frm, text="Search Roots", command=lambda: self._cls_search_roots(self.cls_filter_var.get())).grid(row=0, column=2, sticky=tk.W, padx=6)
        ttk.Button(frm, text="Expand Selected", command=lambda: self._cls_expand_selected()).grid(row=0, column=3, sticky=tk.W, padx=6)
        ttk.Button(frm, text="Add Selected Node", command=lambda: self._cls_add_selected_node()).grid(row=0, column=4, sticky=tk.W, padx=6)
        ttk.Button(frm, text="Add Subtree", command=lambda: self._cls_add_subtree()).grid(row=0, column=5, sticky=tk.W, padx=6)

        pan = ttk.PanedWindow(frm, orient=tk.HORIZONTAL)
        pan.grid(row=1, column=0, columnspan=6, sticky='nsew', padx=8, pady=6)
        frm.grid_rowconfigure(1, weight=1)
        frm.grid_columnconfigure(1, weight=1)

        left = ttk.Frame(pan)
        pan.add(left, weight=3)
        ttk.Label(left, text="Classification tree").pack(anchor='w')
        tree = ttk.Treeview(left, show='tree', height=18)
        tree.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.cls_tree = tree
        self.cls_tree_ids: Dict[str,int] = {}
        self.cls_tree.bind('<<TreeviewOpen>>', lambda e: self._cls_on_open())
        self.cls_tree.bind('<Double-1>', lambda e: self._cls_on_double(e))

        right = ttk.Frame(pan)
        pan.add(right, weight=2)
        ttk.Label(right, text="Selected classifications").pack(anchor='w')
        self.cls_selected = ttk.Treeview(right, columns=("id","name"), show='headings', height=14)
        self.cls_selected.heading('id', text='id')
        self.cls_selected.column('id', width=90, anchor=tk.W)
        self.cls_selected.heading('name', text='name')
        self.cls_selected.column('name', width=320, anchor=tk.W)
        self.cls_selected.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        ttk.Button(right, text="Remove Selected", command=lambda: self._cls_remove_selected()).pack(anchor='e', padx=4, pady=(0,4))

    def _cls_search_roots(self, text: str):
        q = (text or '').strip() or None
        def worker():
            try:
                self.start_busy('Searching classifications…')
                items = self.client.list_classifications(filterText=q, max_results=100, offset=0, orderBy=None, orderDirection=None)
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
                self.log(f"Loaded {count} classification root node(s) for filter {q}")
            except Exception as e:
                messagebox.showerror("Search", str(e))
                self.log("Classification search error: " + str(e))
            finally:
                self.stop_busy()
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
                    self.start_busy('Loading children…')
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
                    self.stop_busy()
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
            # Non-top-level: toggle open/load one level (default behavior)
            is_open = self.cls_tree.item(item, 'open')
            self.cls_tree.item(item, open=(not is_open))
            if not is_open:
                self._cls_load_children_if_needed(item)

    def _cls_expand_full_subtree(self, root_item: str, root_cid: int):
        def worker():
            try:
                self.start_busy('Expanding subtree…')
                stack: List[Tuple[str,int]] = [(root_item, int(root_cid))]
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
                self.stop_busy()
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

    def _cls_add_to_selected(self, ids: List[int]):
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

    def _cls_add_subtree(self):
        sel = self.cls_tree.selection()
        if not sel:
            messagebox.showinfo("Tree", "Select a classification node to add its subtree.")
            return
        item = sel[0]
        root_id = self.cls_tree_ids.get(item)
        if root_id is None:
            messagebox.showerror("Tree", "No id for selected node")
            return
        def worker():
            try:
                self.start_busy('Adding subtree…')
                visited: Set[int] = set()
                stack: List[int] = [int(root_id)]
                calls = 0
                while stack:
                    cid = stack.pop()
                    if cid in visited:
                        continue
                    visited.add(cid)
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
                            if nm:
                                self.cls_name_cache[ccid] = nm
                            stack.append(ccid)
                        except Exception:
                            pass
                    if calls > 5000:
                        self.log("Stopping subtree crawl: too many child fetch calls (5000)")
                        break
                added = self._cls_add_to_selected(sorted(list(visited)))
                nm = self.cls_name_cache.get(root_id) or ''
                self.log(f"Added subtree for {root_id}({nm}): {added} item(s) added, {len(visited)} total unique id(s) in subtree.")
            finally:
                self.stop_busy()
        threading.Thread(target=worker, daemon=True).start()

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

if __name__ == '__main__':
    app = App()
    app.mainloop()
