# IDOR Detection Strategies

## 1. ENUMERATION
- Sequential numeric IDs: try id-1, id+1, id+2, id+10, id+100
- UUID: look for UUID disclosures elsewhere in the app (e.g., `/api/recent-docs`)
- Encoded IDs: try decoding (base64, hex, URL encoding), mutate, re-encode

## 2. PARAMETER LOCATIONS (check ALL)
- URL path segments: `/api/users/{id}/profile`
- Query parameters: `?order_id=123`
- Request body (JSON): `{"message_id": 456}`
- Custom headers: `X-Account-Id: 789`, `X-User-Id: 42`
- Cookies: `current_user_id=42`

## 3. HTTP METHOD VARIATION
- If GET is authenticated, try POST/PUT/DELETE/PATCH on same path
- Sometimes only one method has the authorization check

## 4. CONTEXT MANIPULATION
- Switch between User A and User B sessions
- Try unauthenticated requests (no cookies/headers)
- Try with other users' IDs from discovery

## 5. RESPONSE ANALYSIS
- Compare response sizes (different by user → potential IDOR)
- Compare status codes (200 for both → suspect; 403 for one → secure)
- Look for User B's PII (email, name, phone) in User A's response
- Look for user-specific internal IDs or account data

## 6. GRAPHQL SPECIFIC
- If GraphQL endpoint detected, query: `{ user(id: 2) { email name } }`
- Try introspection: `{ __schema { types { name } } }`
- Test mutations accepting user IDs

## 7. COMMON FALSE POSITIVES (ignore these)
- 429 Too Many Requests → rate limiting, not IDOR
- 503 Service Unavailable → server issue
- 302 Redirect to login → properly authenticated
- Empty 200 response → endpoint exists but no data (not IDOR)
- Error message "not found" → properly enforced (no IDOR)

## 8. HIGH-VALUE TARGETS
Focus on endpoints that:
- Return sensitive data (email, phone, address, payment info)
- Accept a simple numeric ID or UUID
- Are used for "my profile", "my orders", "my documents"
- Include `/admin/` but are accessible without admin role
