# Talent onboarding endpoints: lookup, idempotent creates, activate/deactivate

Requested by the talent session (cc-bus 9506d567, 2026-11-13). Burke, 2026-11-13: "fpqbo was meant to support all of the fortium apps. If there's a flaw, let's fix it there." Talent's admitted-partner onboarding calls fpqbo with its own read/write key (fpqbo-api-key-talent, FOR-138, created 2026-11-24).

## 0. Bug found while scoping: `active_only=false` never returns an inactive row

QuickBooks query returns only active name-list records unless the WHERE clause names `Active`. `_active_clause(False)` returns None, so `active_only=false` sends no Active filter and QBO hides inactive rows. Measured in production FOR-138 on 2026-11-24, paging every row with `active_only=false`: accounts 954 rows / 0 inactive, vendors 639 / 0, customers 680 / 0, items 19 / 0.

Fix: `_active_clause(False)` returns `Active IN (true, false)`. That clause holds for every row, so it can only add the inactive rows QBO was hiding. The existing assertion `_active_clause(False) is None` in tests/test_qbo_query_injection.py pins the bug, so it changes.

Verify after deploy: the same paging count shows inactive > 0 for at least one entity.

## 1. Lookup, including inactive records

- `GET /api/vendors/lookup?company_id=N&display_name=X` and/or `&email=Y`. At least one of the two is required (else 400). Returns a JSON array of every matching vendor, active and inactive.
  - display_name: server-side `DisplayName = 'X'` (exact, through `string_equals`, escaped) AND `Active IN (true, false)`.
  - email: QBO cannot filter on PrimaryEmailAddr, so walk all vendors (`_fetch_all_pages`, with `Active IN (true, false)`) and match `PrimaryEmailAddr.Address` case-insensitively, ignoring surrounding whitespace. When both are given, a vendor must match both.
  - If the walk is truncated (has_more true), answer 503 rather than claim no match.
- `GET /api/accounts/lookup?company_id=N&name=X`: server-side `Name = 'X'` AND `Active IN (true, false)`. Returns every match. Account names repeat under different parents, so the caller reads FullyQualifiedName and ParentRef.
- These return a bounded set of exact matches with no cursor, so they join the list-route registry guard's named exceptions with that reason.
- Route order: `/lookup` must be declared before `/{vendor_id}` / `/{account_id}`.

## 2. Idempotent creates: caller-supplied request id

- `POST /api/vendors/`, `POST /api/accounts/`, `POST /api/vendor-credits/` accept an optional `Request-Id` header. It's passed to the SDK as `save(qb=client, request_id=...)`, which sends it to QBO as the `requestid` query parameter. QBO answers a repeat of the same requestid with the original result instead of creating a second record.
- Validation at the boundary: 1 to 50 characters, `[A-Za-z0-9_-]`. Anything else is 400 before any QBO call. Absent means the old behaviour, unchanged.
- Creates stay on `asyncio.to_thread`, never the retry helper.

## 3. Activate / deactivate

- `POST /api/vendors/{id}/activate`, `POST /api/vendors/{id}/deactivate`, `POST /api/accounts/{id}/activate`, `POST /api/accounts/{id}/deactivate`.
- Fetch the record by id (`_fetch_by_id`, 404 when missing), then send a sparse update `{Id, SyncToken, sparse: true, Active: <bool>}` through the same client.post pattern as `update_bill`. Return the updated entity.
- Idempotent: when the record is already in the requested state, return it unchanged without a write.
- No `Request-Id` (changed after /code-review high): QBO replays the first answer for a repeated requestid, so a deactivate then activate under one id would silently do nothing. The already-in-state check makes these idempotent without it.
- QBO refusals: 5010 (stale SyncToken) is 409; any other refusal of the update (e.g. 6240, a reactivated name colliding with an active one) is 400.
- They're write routes, so a read-only key gets 403 from the existing gate.

## Docs

The CLAUDE.md endpoint table gains the six routes and the Request-Id note. The key table gains the PartnerConnect US/CA write keys and the Talent key.

## Tests (red first)

- `_active_clause(False) == "Active IN (true, false)"`. Fails on main.
- Vendor lookup by display name builds the escaped exact clause plus the Active IN clause. Lookup by email matches case-insensitively across pages, and its answer includes an inactive vendor. A truncated walk gives 503. With neither param, 400.
- Account lookup by name builds an exact, escaped clause and returns every match.
- Request-Id reaches `save(request_id=...)` for all three creates. An invalid id is 400 with no save. With no header, save gets `request_id=None`.
- Activate/deactivate sends a sparse body with Id, SyncToken and Active. When the record is already in the requested state, there's no write. A missing id is 404. A read-only key is refused.
- Route-order test: `/api/vendors/lookup` is not swallowed by `/{vendor_id}`.
