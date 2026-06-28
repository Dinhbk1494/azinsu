import json
import uuid
from datetime import datetime
from agent.tools.base import BaseTool, checked_request


def _extract_fields(body_text: str, known_data: dict) -> tuple[list[str], dict]:
    found_fields = []
    extracted = {}
    try:
        body = json.loads(body_text)
        flat = _flatten(body)
        for key, value in flat.items():
            for dk, dv in known_data.items():
                if str(dv) and str(dv).lower() in str(value).lower():
                    found_fields.append(f"{key}={value}")
                    extracted[key] = value
    except Exception:
        for dk, dv in known_data.items():
            if str(dv) and str(dv) in body_text:
                found_fields.append(f"{dk} value found in response")
                extracted[dk] = dv
    return found_fields, extracted


def _flatten(obj, prefix="") -> dict:
    result = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            full_key = f"{prefix}.{k}" if prefix else k
            result.update(_flatten(v, full_key))
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:5]):
            result.update(_flatten(v, f"{prefix}[{i}]"))
    else:
        result[prefix] = obj
    return result


class IdorConfirmTool(BaseTool):
    name = "idor_confirm"

    def run(self, candidate: dict, user_a_auth: dict, user_b_auth: dict, user_b_known_data: dict = None) -> dict:
        user_b_known_data = user_b_known_data or {}

        url = candidate["url"]
        method = candidate.get("method", "GET")
        mutated_value = candidate["mutated_value"]
        param = candidate["vulnerable_param"]
        location = candidate["param_location"]
        q_params = candidate.get("param_in_query", {})
        b_params = candidate.get("param_in_body")
        h_params = candidate.get("param_in_headers", {})

        a_cookies = user_a_auth.get("cookies", {})
        a_headers = user_a_auth.get("headers", {})
        b_cookies = user_b_auth.get("cookies", {})
        b_headers = user_b_auth.get("headers", {})

        def do_request(cookies, headers):
            kwargs = dict(cookies=cookies, headers=headers, timeout=self.timeout)
            final_url = url
            if location == "path":
                final_url = url  # URL already has mutated value substituted
            elif location == "query":
                kwargs["params"] = {**q_params, param: mutated_value}
            elif location == "body":
                payload = dict(b_params or {})
                payload[param] = mutated_value
                kwargs["json"] = payload
            elif location == "header":
                kwargs["headers"] = {**headers, **h_params, param: mutated_value}
            elif location == "cookie":
                kwargs["cookies"] = {**cookies, param: mutated_value}
            if b_params and location not in ("body",):
                kwargs["json"] = b_params
            return checked_request(method, final_url, **kwargs)

        # Run 3 times: user_a (main test), user_b (baseline), user_a again (consistency)
        try:
            resp_a1 = do_request(a_cookies, a_headers)
            resp_b = do_request(b_cookies, b_headers)
        except Exception as e:
            return {"confirmed": False, "confidence": 0.0, "error": str(e)}

        # Check if user A's response looks like user B's
        a1_text = resp_a1.text
        b_text = resp_b.text

        fields_found, extracted = _extract_fields(a1_text, user_b_known_data)
        confirmed = False
        method_name = ""
        confidence = 0.0

        if fields_found:
            confirmed = True
            method_name = "user_b_data_extracted"
            confidence = 0.95
        elif resp_a1.status_code == 200 and resp_b.status_code == 200:
            # Same-length check
            size_diff = abs(len(a1_text) - len(b_text))
            if size_diff < 50 and len(a1_text) > 10:
                # Responses are similar in size — likely same data structure
                confirmed = True
                method_name = "similar_response_structure"
                confidence = 0.6
                # Extract any data we found
                try:
                    body_a = json.loads(a1_text)
                    extracted = body_a if isinstance(body_a, dict) else {"data": body_a}
                except Exception:
                    extracted = {"raw": a1_text[:200]}

        # Consistency check (re-run if confirmed)
        if confirmed:
            try:
                resp_a2 = do_request(a_cookies, a_headers)
                if resp_a2.status_code != resp_a1.status_code:
                    confidence *= 0.7  # Less confident if inconsistent
            except Exception:
                pass

        evidence = None
        if confirmed and extracted:
            evidence = {
                "unauthorized_data": extracted,
                "user_b_fields_found": fields_found,
                "raw_response_excerpt": a1_text[:500],
            }

        poc_req = {
            "method": method,
            "url": url,
            "headers": a_headers,
            "cookies": a_cookies,
            "body": b_params,
        }
        poc_resp = {
            "status_code": resp_a1.status_code,
            "body": a1_text[:1000],
            "headers": dict(resp_a1.headers),
        }

        return {
            "confirmed": confirmed,
            "evidence": evidence,
            "poc_request": poc_req,
            "poc_response": poc_resp,
            "confidence": confidence,
            "confirmation_method": method_name,
        }
