import re
import json
from urllib.parse import urljoin, urlparse
from agent.tools.base import BaseTool, checked_request

ID_PATTERNS = re.compile(
    r'(?i)(\b(?:user_?id|account_?id|order_?id|doc_?id|file_?id|'
    r'message_?id|post_?id|comment_?id|object_?id|resource_?id|'
    r'invoice_?id|ticket_?id|id)\b|/\d+/?|/[0-9a-f-]{36}/?)'
)

API_REGEX = re.compile(r'''(?:fetch|axios\.get|axios\.post|\.get|\.post|\.put|\.delete|\.patch)\s*\(\s*[`'"](\/[^`'"]+)''')


def looks_like_id(name: str, value: str) -> bool:
    name_l = name.lower()
    if any(x in name_l for x in ("_id", "id_", "userid", "accountid", "orderid", "uuid", "guid")):
        return True
    if name_l in ("id", "ref", "key", "token", "slug"):
        return True
    if value and (value.isdigit() or re.match(r'^[0-9a-f-]{36}$', value)):
        return True
    return False


class EndpointDiscoverTool(BaseTool):
    name = "endpoint_discover"

    def run(self, base_url: str, auth: dict = None, max_depth: int = 3, include_graphql: bool = True) -> dict:
        auth = auth or {}
        cookies = auth.get("cookies", {})
        headers = auth.get("headers", {})

        visited: set[str] = set()
        endpoints: list[dict] = []
        id_params: list[dict] = []
        queue = [(base_url, 0)]

        while queue:
            url, depth = queue.pop(0)
            if url in visited or depth > max_depth:
                continue
            visited.add(url)

            try:
                resp = checked_request("GET", url, cookies=cookies, headers=headers, timeout=self.timeout)
            except Exception:
                continue

            content_type = resp.headers.get("content-type", "")

            # Parse HTML
            if "html" in content_type:
                self._parse_html(resp.text, url, base_url, endpoints, id_params, visited, queue, depth, cookies, headers)

            # Parse JSON API response
            elif "json" in content_type:
                ep = self._make_endpoint(url, "GET", resp.text)
                if ep:
                    endpoints.append(ep)

        # Probe common API paths
        self._probe_common_paths(base_url, cookies, headers, endpoints, id_params)

        # GraphQL
        if include_graphql:
            self._probe_graphql(base_url, cookies, headers, endpoints)

        # Deduplicate
        seen = set()
        unique_endpoints = []
        for ep in endpoints:
            key = ep["method"] + ":" + ep["url"]
            if key not in seen:
                seen.add(key)
                unique_endpoints.append(ep)

        return {
            "endpoints": unique_endpoints,
            "parameters_with_id_indicators": id_params,
        }

    def _make_endpoint(self, url: str, method: str, body_text: str = "") -> dict | None:
        params = []
        # Extract path params that look like IDs
        parts = urlparse(url).path.split("/")
        for part in parts:
            if part.isdigit() or re.match(r'^[0-9a-f-]{36}$', part):
                params.append({"name": "id", "location": "path", "sample_value": part, "looks_like_id": True})
        return {"url": url, "method": method, "parameters": params, "requires_auth": True, "is_graphql": False}

    def _parse_html(self, html: str, current_url: str, base_url: str,
                    endpoints: list, id_params: list, visited: set, queue: list,
                    depth: int, cookies: dict, headers: dict):
        from bs4 import BeautifulSoup
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            return

        # Links
        for a in soup.find_all("a", href=True):
            href = urljoin(current_url, a["href"])
            if href.startswith(base_url) and href not in visited:
                queue.append((href, depth + 1))

        # Forms
        for form in soup.find_all("form"):
            action = urljoin(current_url, form.get("action", current_url))
            method = form.get("method", "GET").upper()
            params = []
            for inp in form.find_all(["input", "select", "textarea"]):
                name = inp.get("name", "")
                value = inp.get("value", "")
                if name:
                    is_id = looks_like_id(name, value)
                    p = {"name": name, "location": "body", "sample_value": value, "looks_like_id": is_id}
                    params.append(p)
                    if is_id:
                        id_params.append(p)
            endpoints.append({"url": action, "method": method, "parameters": params, "requires_auth": True, "is_graphql": False})

        # Scripts - mine API endpoints
        for script in soup.find_all("script"):
            src = script.get("src")
            if src:
                js_url = urljoin(current_url, src)
                if js_url.startswith(base_url) and js_url not in visited:
                    try:
                        js_resp = checked_request("GET", js_url, cookies=cookies, headers=headers, timeout=self.timeout)
                        self._mine_js(js_resp.text, base_url, endpoints, id_params)
                    except Exception:
                        pass
            elif script.string:
                self._mine_js(script.string, base_url, endpoints, id_params)

    def _mine_js(self, js_text: str, base_url: str, endpoints: list, id_params: list):
        for match in API_REGEX.finditer(js_text):
            path = match.group(1)
            full_url = base_url.rstrip("/") + path
            # Replace path params like :id or {id} with placeholder
            normalized = re.sub(r'[:{}]\w+', '{id}', path)
            ep = {
                "url": base_url.rstrip("/") + normalized,
                "method": "GET",
                "parameters": [{"name": "id", "location": "path", "sample_value": "1", "looks_like_id": True}] if "{id}" in normalized else [],
                "requires_auth": True,
                "is_graphql": False,
            }
            endpoints.append(ep)

    def _probe_common_paths(self, base_url: str, cookies: dict, headers: dict, endpoints: list, id_params: list):
        common = [
            ("/api/users/1", "GET"),
            ("/api/users/2", "GET"),
            ("/api/profile", "GET"),
            ("/api/orders/1", "GET"),
            ("/api/account", "GET"),
            ("/api/invoices/1", "GET"),
            ("/api/messages", "GET"),
            ("/api/docs/1", "GET"),
            ("/api/files/1", "GET"),
            ("/api/admin/users", "GET"),
            ("/rest/user/whoami", "GET"),
            ("/rest/basket/1", "GET"),
        ]
        for path, method in common:
            url = base_url.rstrip("/") + path
            try:
                resp = checked_request(method, url, cookies=cookies, headers=headers, timeout=10)
                if resp.status_code not in (404, 405, 500, 502, 503):
                    ep = self._make_endpoint(url, method)
                    if ep:
                        endpoints.append(ep)
            except Exception:
                pass

    def _probe_graphql(self, base_url: str, cookies: dict, headers: dict, endpoints: list):
        gql_paths = ["/graphql", "/api/graphql", "/gql", "/query"]
        introspection = {"query": "{ __schema { queryType { name } } }"}
        for path in gql_paths:
            url = base_url.rstrip("/") + path
            try:
                resp = checked_request("POST", url, json=introspection, cookies=cookies, headers=headers, timeout=10)
                if resp.status_code == 200:
                    endpoints.append({
                        "url": url,
                        "method": "POST",
                        "parameters": [{"name": "query", "location": "body", "sample_value": "", "looks_like_id": False}],
                        "requires_auth": True,
                        "is_graphql": True,
                    })
            except Exception:
                pass
