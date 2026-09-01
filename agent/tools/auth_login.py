import time
from agent.tools.base import BaseTool, checked_request


class AuthLoginTool(BaseTool):
    name = "auth_login"

    def run(self, base_url: str, credentials: dict,
            login_endpoint: str = "/api/login",
            method: str = "POST",
            auth_type: str = "json") -> dict:

        url = base_url.rstrip("/") + login_endpoint

        cookies = {}
        token_headers = {}

        # Try JSON body first
        try:
            if auth_type in ("json", "oauth"):
                resp = checked_request(method, url, json=credentials, timeout=self.timeout)
            elif auth_type == "form":
                resp = checked_request(method, url, data=credentials, timeout=self.timeout)
            elif auth_type == "basic":
                user = credentials.get("username") or credentials.get("email", "")
                pw = credentials.get("password", "")
                resp = checked_request(method, url, auth=(user, pw), timeout=self.timeout)
            else:
                resp = checked_request(method, url, json=credentials, timeout=self.timeout)
        except Exception as e:
            return {"success": False, "error": str(e), "cookies": {}, "headers": {}}

        cookies = dict(resp.cookies)
        user_info = None

        # Extract token from response body
        try:
            body = resp.json()
            for key in ("token", "access_token", "accessToken", "jwt", "auth_token"):
                if key in body:
                    token_headers["Authorization"] = f"Bearer {body[key]}"
                    break
            # Try to extract user info
            for key in ("user", "data", "account", "profile"):
                if key in body and isinstance(body[key], dict):
                    user_info = body[key]
                    break
            if user_info is None and "id" in body:
                user_info = {k: body[k] for k in ("id", "email", "username", "name", "role") if k in body}
        except Exception:
            pass

        # If JSON login failed, try form-encoded
        if resp.status_code >= 400 and auth_type == "json":
            try:
                resp2 = checked_request(method, url, data=credentials, timeout=self.timeout)
                if resp2.status_code < 400:
                    resp = resp2
                    cookies = dict(resp.cookies)
            except Exception:
                pass

        success = resp.status_code < 400 and (bool(cookies) or bool(token_headers))

        return {
            "success": success,
            "cookies": cookies,
            "headers": token_headers,
            "user_info": user_info,
            "status_code": resp.status_code,
            "error": None if success else f"HTTP {resp.status_code}",
        }
