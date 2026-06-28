import json
from agent.tools.base import BaseTool, checked_request


def _body_excerpt(text: str, max_len: int = 500) -> str:
    return text[:max_len] if len(text) > max_len else text


def _compare_responses(results: list[dict]) -> tuple[list[dict], bool, float]:
    differences = []
    if len(results) < 2:
        return differences, False, 0.0

    ref = results[0]
    for other in results[1:]:
        if ref["status_code"] != other["status_code"]:
            differences.append({
                "field": "status_code",
                "value_a": str(ref["status_code"]),
                "value_b": str(other["status_code"]),
            })
        size_diff = abs(ref["response_length"] - other["response_length"])
        if size_diff > 20:
            differences.append({
                "field": "response_length",
                "value_a": str(ref["response_length"]),
                "value_b": str(other["response_length"]),
            })

        # Try JSON diff
        try:
            body_a = json.loads(ref["body_excerpt"])
            body_b = json.loads(other["body_excerpt"])
            for key in set(list(body_a.keys()) + list(body_b.keys())):
                va = str(body_a.get(key, "MISSING"))
                vb = str(body_b.get(key, "MISSING"))
                if va != vb:
                    differences.append({"field": key, "value_a": va[:100], "value_b": vb[:100]})
        except Exception:
            pass

    # Heuristic: if 2+ contexts both get 200 with different body content → suspect IDOR
    both_200 = all(r["status_code"] == 200 for r in results)
    body_differs = any(d["field"] in ("response_length",) or "id" in d["field"].lower() for d in differences)
    suggests_idor = both_200 and bool(differences)
    confidence = 0.7 if suggests_idor and body_differs else (0.4 if suggests_idor else 0.0)

    return differences, suggests_idor, confidence


class AuthCompareTool(BaseTool):
    name = "auth_compare"

    def run(self, url: str, method: str = "GET",
            path_params: dict = None, query_params: dict = None,
            body: dict = None, request_headers: dict = None,
            auth_contexts: list[dict] = None) -> dict:

        path_params = path_params or {}
        query_params = query_params or {}
        request_headers = request_headers or {}
        auth_contexts = auth_contexts or []

        # Substitute path params
        final_url = url
        for k, v in path_params.items():
            final_url = final_url.replace("{" + k + "}", str(v))

        results = []
        for ctx in auth_contexts:
            label = ctx.get("label", "unknown")
            cookies = ctx.get("cookies", {})
            ctx_headers = {**request_headers, **ctx.get("headers", {})}

            kwargs = dict(
                params=query_params or None,
                cookies=cookies,
                headers=ctx_headers,
                timeout=self.timeout,
            )
            if body is not None:
                kwargs["json"] = body

            try:
                resp = checked_request(method, final_url, **kwargs)
                body_text = resp.text
                results.append({
                    "auth_label": label,
                    "status_code": resp.status_code,
                    "response_length": len(body_text),
                    "body_excerpt": _body_excerpt(body_text),
                    "headers": dict(resp.headers),
                })
            except Exception as e:
                results.append({
                    "auth_label": label,
                    "status_code": 0,
                    "response_length": 0,
                    "body_excerpt": f"ERROR: {e}",
                    "headers": {},
                })

        differences, suggests_idor, confidence = _compare_responses(results)

        return {
            "results": results,
            "differences": differences,
            "suggests_idor": suggests_idor,
            "confidence": confidence,
        }
