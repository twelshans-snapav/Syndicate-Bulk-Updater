#!/usr/bin/env python3
# syndicate_client.py
# Syndicate API client — authentication, documents, folders, attributes, classifications

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

try:
    import requests
except Exception:
    requests = None


@dataclass
class Auth:
    domain: str
    header_name: str
    token: str


class Client:
    def __init__(self):
        self.auth: Optional[Auth] = None
        self.session = requests.Session() if requests else None
        self.timeout = None  # No per-request timeout; inactivity sign-out handled by the UI
        self._creds: Optional[Tuple[str, str, str]] = None  # (domain, username, password)

    def _require(self):
        if not requests:
            raise RuntimeError("Install requests: pip install requests")
        if not self.session:
            raise RuntimeError("requests session not available")
        if not self.auth:
            raise RuntimeError("Session expired — please re-authenticate")

    def base(self, domain: str) -> str:
        return "https://core-" + domain + ".bravais.com/api/v3"

    # ---------- Auth ----------

    def authenticate(self, domain: str, username: str, password: str) -> Auth:
        if not requests:
            raise RuntimeError("Install requests: pip install requests")
        if not self.session:
            raise RuntimeError("requests session not available")
        # Note: intentionally no self.auth check — this method establishes auth
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
        self._creds = (domain, username, password)  # store for transparent re-auth on 401
        return self.auth

    def _reauthenticate(self) -> bool:
        """Re-authenticate using stored credentials. Returns True on success."""
        if not self._creds:
            return False
        try:
            domain, username, password = self._creds
            self.authenticate(domain, username, password)
            return True
        except Exception:
            return False

    def _req(self, fn: Callable) -> 'requests.Response':
        """Execute fn() (a zero-arg callable that returns a Response).
        On 401, transparently re-authenticate and retry once."""
        r = fn()
        if r.status_code == 401 and self._creds:
            if self._reauthenticate():
                r = fn()  # fn() re-calls self._h(), picking up the new token
        return r

    def _h(self) -> Dict[str, str]:
        if not self.auth:
            raise RuntimeError("Not authenticated")
        return {self.auth.header_name: self.auth.token, 'Accept': 'application/json'}

    # ---------- Docs & Folders ----------

    def get_document(self, doc_id: Union[int, str], include_custom: bool = True, include_classifications: bool = True) -> Dict[str, Any]:
        self._require()
        url = self.base(self.auth.domain) + f"/documents/{doc_id}"
        params = []
        if include_custom:
            params.append(("includeCustomAttributes", "true"))
        if include_classifications:
            params.append(("includeClassifications", "true"))
        r = self._req(lambda: self.session.get(url, headers=self._h(), params=params or None, timeout=self.timeout))
        if r.status_code >= 400:
            raise RuntimeError(f"Document fetch failed ({r.status_code}): {r.text or ''}")
        return r.json()

    def get_items(self, folder_id: Union[int, str], *, max_results: int = 50, offset: int = 0, filterText: Optional[str] = None) -> List[Dict[str, Any]]:
        self._require()
        url = self.base(self.auth.domain) + f"/folders/{folder_id}/items"
        params: Dict[str, Any] = {"max": max_results, "offset": offset, "includeCustomAttributes": "true", "includeClassifications": "true"}
        if filterText:
            params['filterText'] = filterText
        r = self._req(lambda: self.session.get(url, headers=self._h(), params=params, timeout=self.timeout))
        if r.status_code >= 400:
            raise RuntimeError(f"Items failed ({r.status_code}): {r.text or ''}")
        data = r.json()
        return data if isinstance(data, list) else (data.get('items', []) if isinstance(data, dict) else [])

    def get_subfolders_page(self, folder_id: Union[int, str], *, max_results: int = 200, offset: int = 0) -> List[Dict[str, Any]]:
        self._require()
        url = self.base(self.auth.domain) + f"/folders/{folder_id}/subfolders"
        params = {"max": max_results, "offset": offset, "folderPath": "true"}
        r = self._req(lambda: self.session.get(url, headers=self._h(), params=params, timeout=self.timeout))
        if r.status_code >= 400:
            raise RuntimeError(f"Subfolders failed ({r.status_code}): {r.text or ''}")
        data = r.json()
        return data if isinstance(data, list) else (data.get('items', []) if isinstance(data, dict) else [])

    def get_subfolders_all(self, folder_id: Union[int, str], *, page_size: int = 200) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
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

    def list_custom_attributes(self, *, filterText: Optional[str] = None, max_results: int = 200, offset: int = 0,
                               orderBy: Optional[str] = 'name', orderDirection: Optional[str] = 'asc') -> List[Dict[str, Any]]:
        self._require()
        url = self.base(self.auth.domain) + "/customAttributes"
        params: Dict[str, Any] = {}
        if filterText: params['filterText'] = filterText
        if max_results: params['max'] = max_results
        if offset: params['offset'] = offset
        if orderBy: params['orderBy'] = orderBy
        if orderDirection: params['orderDirection'] = orderDirection
        r = self._req(lambda: self.session.get(url, headers=self._h(), params=params, timeout=self.timeout))
        if r.status_code >= 400:
            raise RuntimeError(f"Custom attributes list failed ({r.status_code}): {r.text or ''}")
        data = r.json()
        return data if isinstance(data, list) else (data.get('items', []) if isinstance(data, dict) else [])

    def list_all_custom_attributes_safe(self, *, page_size: int = 200) -> List[Dict[str, Any]]:
        out: Dict[int, Dict[str, Any]] = {}
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

    def post_version_attr(self, version_id: Union[int, str], attr_id: int, value: str) -> Dict[str, Any]:
        self._require()
        url = self.base(self.auth.domain) + f"/documentVersions/{version_id}/customAttributes/{attr_id}"
        r = self._req(lambda: self.session.post(url, headers={**self._h(), 'Content-Type': 'application/json'}, params={"value": value}, timeout=self.timeout))
        if r.status_code >= 400:
            raise RuntimeError(f"Update failed ({r.status_code}): {r.text or ''}")
        try:
            return r.json() if r.content else {}
        except Exception:
            return {"raw": r.text or ''}

    # ---------- Classifications ----------

    def list_root_classifications(self) -> List[Dict[str, Any]]:
        self._require()
        url = self.base(self.auth.domain) + "/classifications/roots"
        r = self._req(lambda: self.session.get(url, headers=self._h(), timeout=self.timeout))
        if r.status_code >= 400:
            raise RuntimeError(f"Root classifications failed ({r.status_code}): {r.text or ''}")
        data = r.json()
        return data if isinstance(data, list) else (data.get('items', []) if isinstance(data, dict) else [])

    def list_classifications(self, *, filterText: Optional[str] = None, max_results: int = 200, offset: int = 0,
                             orderBy: Optional[str] = 'name', orderDirection: Optional[str] = 'asc') -> List[Dict[str, Any]]:
        self._require()
        url = self.base(self.auth.domain) + "/classifications"
        params: Dict[str, Any] = {}
        if filterText: params['filterText'] = filterText
        if max_results: params['max'] = max_results
        if offset: params['offset'] = offset
        if orderBy: params['orderBy'] = orderBy
        if orderDirection: params['orderDirection'] = orderDirection
        r = self._req(lambda: self.session.get(url, headers=self._h(), params=params, timeout=self.timeout))
        if r.status_code >= 400:
            raise RuntimeError(f"Classifications list failed ({r.status_code}): {r.text or ''}")
        data = r.json()
        return data if isinstance(data, list) else (data.get('items', []) if isinstance(data, dict) else [])

    def list_class_children(self, classification_id: Union[int, str]) -> List[Dict[str, Any]]:
        self._require()
        url = self.base(self.auth.domain) + f"/classifications/{classification_id}/children"
        r = self._req(lambda: self.session.get(url, headers=self._h(), timeout=self.timeout))
        if r.status_code == 404:
            return []
        if r.status_code >= 400:
            raise RuntimeError(f"Class children failed ({r.status_code}): {r.text or ''}")
        data = r.json()
        return data if isinstance(data, list) else (data.get('items', []) if isinstance(data, dict) else [])

    def update_document(self, doc_id: Union[int, str], name: str) -> Dict[str, Any]:
        self._require()
        url = self.base(self.auth.domain) + f"/documents/{doc_id}"
        r = self._req(lambda: self.session.put(url, headers={**self._h(), 'Content-Type': 'application/json'}, json={"name": name}, timeout=self.timeout))
        if r.status_code >= 400:
            raise RuntimeError(f"Update document failed ({r.status_code}): {r.text or ''}")
        try:
            return r.json() if r.content else {}
        except Exception:
            return {"raw": r.text or ''}

    def set_document_classifications(self, doc_id: Union[int, str], class_ids: List[int], *, replace_all: bool = True) -> Dict[str, Any]:
        self._require()
        url = self.base(self.auth.domain) + f"/documents/{doc_id}/classifications"
        params = {'replaceAll': 'true' if replace_all else 'false'}
        r = self._req(lambda: self.session.post(url, headers={**self._h(), 'Content-Type': 'application/json'}, params=params, json=(class_ids or []), timeout=self.timeout))
        if r.status_code >= 400:
            raise RuntimeError(f"Set classifications failed ({r.status_code}): {r.text or ''}")
        try:
            return r.json() if r.content else {}
        except Exception:
            return {"raw": r.text or ''}
