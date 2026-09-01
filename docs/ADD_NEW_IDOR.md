# How to Add a New IDOR Variation

## 1. Add the endpoint to custom-idor-lab

In `lab/custom-idor-lab/app.py`, add a new route:

```python
@app.route('/api/your-endpoint/<int:resource_id>', methods=['GET'])
@require_auth
def your_endpoint(resource_id):
    # VULNERABLE: no ownership check
    resource = Resource.query.get_or_404(resource_id)
    return jsonify(resource.to_dict())
```

## 2. Add ground truth entry

In `lab/ground_truth/custom-idor-lab.json`, add to the `idors` array:

```json
{
  "id": "CUSTOM-IDOR-21",
  "idor_number": 21,
  "type": "your_idor_type",
  "endpoint": "/api/your-endpoint/{resource_id}",
  "method": "GET",
  "description": "Clear description of the vulnerability",
  "vulnerable_param": "resource_id",
  "param_location": "path",
  "test_with_id": 2,
  "evidence_field": "user_id",
  "difficulty": "medium"
}
```

## 3. Add seed data

In `lab/custom-idor-lab/data/seed.py`, add data for both userA and userB.

## 4. Verify it works

```bash
python lab/scripts/verify_truth.py
```

## 5. IDOR types

| Type | Description |
|------|-------------|
| `numeric_id_in_path` | `/api/users/{id}` |
| `numeric_id_in_query` | `?order_id=123` |
| `id_in_request_body` | `{"user_id": 2}` |
| `id_in_custom_header` | `X-Account-Id: 2` |
| `id_in_cookie` | Cookie `user_id=2` |
| `sequential_enumeration` | Sequential numeric IDs |
| `uuid_enumeration_via_leak` | UUID leaked from another endpoint |
| `base64_encoded_id` | `?ref=Mg==` (base64 of "2") |
| `hex_encoded_id` | `/resource/0x2` |
| `graphql_idor` | GraphQL query without auth |
| `http_method_bypass` | GET protected, POST not |
| `mass_assignment` | `{"user_id": 2, "name": "x"}` |
| `predictable_slug` | `user_2_doc_1` |
| `referer_bypass` | Spoofed Referer header |
