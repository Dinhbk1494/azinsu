"""PortSwigger Web Academy adapter using Playwright."""
import os
import json
from typing import Optional


PORTSWIGGER_LABS = [
    {"id": "ac-01", "name": "Unprotected admin functionality", "slug": "unprotected-admin-functionality"},
    {"id": "ac-02", "name": "Unprotected admin with unpredictable URL", "slug": "unprotected-admin-functionality-with-unpredictable-url"},
    {"id": "ac-03", "name": "User role via request parameter", "slug": "user-role-controlled-by-request-parameter"},
    {"id": "ac-04", "name": "User role modifiable in profile", "slug": "user-role-can-be-modified-in-user-profile"},
    {"id": "ac-05", "name": "IDOR via user ID parameter", "slug": "user-id-controlled-by-request-parameter-with-unpredictable-user-ids"},
    {"id": "ac-06", "name": "IDOR with unpredictable user IDs", "slug": "user-id-controlled-by-request-parameter"},
    {"id": "ac-07", "name": "IDOR with data leakage in redirect", "slug": "user-id-controlled-by-request-parameter-with-data-leakage-in-redirect"},
    {"id": "ac-08", "name": "IDOR with password disclosure", "slug": "user-id-controlled-by-request-parameter-with-password-disclosure"},
    {"id": "ac-09", "name": "Insecure direct object references", "slug": "insecure-direct-object-references"},
    {"id": "ac-10", "name": "URL-based access control bypass", "slug": "url-based-access-control-can-be-circumvented"},
    {"id": "ac-11", "name": "Method-based access control bypass", "slug": "method-based-access-control-can-be-circumvented"},
    {"id": "ac-12", "name": "Multi-step process access control", "slug": "multi-step-process-with-no-access-control-on-one-step"},
    {"id": "ac-13", "name": "Referer-based access control", "slug": "referer-based-access-control"},
]


def run_portswigger_lab(lab: dict, email: str, password: str) -> Optional[dict]:
    """Open a PortSwigger lab, run agent, check if solved."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"error": "playwright not installed", "solved": False}

    account_email = os.environ.get("PORTSWIGGER_EMAIL", email)
    account_password = os.environ.get("PORTSWIGGER_PASSWORD", password)

    if not account_email or not account_password:
        return {"error": "PORTSWIGGER_EMAIL and PORTSWIGGER_PASSWORD env vars required", "solved": False}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        try:
            # Login
            page.goto("https://portswigger.net/users/sign-in")
            page.fill("#username-input", account_email)
            page.fill("#password-input", account_password)
            page.click("[type=submit]")
            page.wait_for_load_state("networkidle")

            # Open lab
            lab_url = f"https://portswigger.net/web-security/access-control/lab-{lab['slug']}"
            page.goto(lab_url)

            # Click "Access the Lab"
            try:
                page.click("text=Access the lab", timeout=5000)
                page.wait_for_load_state("networkidle")
            except Exception:
                pass

            target_url = page.url
            if "web-security-academy.net" not in target_url:
                return {"error": "Could not get lab URL", "solved": False, "lab_id": lab["id"]}

            # Get lab credentials if visible on page
            lab_user = {"email": "wiener", "password": "peter", "label": "userA"}
            creds_text = page.inner_text("body")
            import re
            users_m = re.search(r'Your credentials.*?(\w+)\s*/\s*(\w+)', creds_text)
            if users_m:
                lab_user["email"] = users_m.group(1)
                lab_user["password"] = users_m.group(2)

            # Run agent against lab URL
            import subprocess, tempfile, json
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
                json.dump([lab_user, {"email": "carlos", "password": "montoya", "label": "userB"}], f)
                users_file = f.name

            import os
            subprocess.run(
                ["python", "agent/main.py", "--target", target_url, "--users", users_file,
                 "--max-steps", "30"],
                timeout=300,
                cwd=str(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
            )
            os.unlink(users_file)

            # Check if lab is solved
            page.reload()
            page.wait_for_load_state("networkidle")
            solved = "congratulations" in page.inner_text("body").lower()

            return {"lab_id": lab["id"], "solved": solved, "target_url": target_url}

        except Exception as e:
            return {"lab_id": lab["id"], "solved": False, "error": str(e)}
        finally:
            browser.close()


def run_portswigger_suite(email: str = "", password: str = "") -> list[dict]:
    """Run all PortSwigger Access Control labs."""
    results = []
    for lab in PORTSWIGGER_LABS:
        print(f"[*] Running PortSwigger lab: {lab['name']}")
        result = run_portswigger_lab(lab, email, password)
        results.append(result or {"lab_id": lab["id"], "solved": False, "error": "No result"})
        print(f"  → {'SOLVED' if result and result.get('solved') else 'FAILED'}")
    return results
