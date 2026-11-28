# Talent gaps, round 2: vendor-credit doc_number filter, Vendor1099 passthrough, QBO refusals as 4xx

Requested by talent (cc-bus 0977f039, f5ba0062, fbad7f6c, 2026-11-24) for talent#1221's admitted-partner onboarding.

## 1. `GET /api/vendor-credits/?doc_number=` actually filters

Today the list route has no `doc_number` parameter, and FastAPI ignores unknown query params. So `?doc_number=X` returns 200 with every credit. Verified in prod 2026-11-25. Talent's "find the credit before creating" step would read any credit as a match and never issue one.

- Add `doc_number: str | None` to `list_vendor_credits`. When it's given, the QBO WHERE is `DocNumber = '<escaped>'` through `string_equals`, combined with the existing date clause by AND. It still pages with the usual headers.
- A blank or whitespace value is 400.
- Tests: the clause is built escaped. A blank value is 400 with no QBO call. With no param, the clause is unchanged. The route's OpenAPI lists `doc_number`.

## 2. `Vendor1099` passthrough on `POST /api/vendors/`

`create_vendor` copies a fixed field list, and `Vendor1099` isn't on it. The SDK's `Vendor()` sets `Vendor1099 = False` in `__init__`, so today every vendor created through the API is created explicitly non-1099.

- Copy `Vendor1099` when the body has it.
- Tests: `Vendor1099: true` reaches the saved object as True. When it's absent, the object keeps the SDK default. That pins the current behaviour; it's not changed silently.

## 3. QBO refusals on write routes become 4xx, not 500

`run_qbo_write` (app/routers/_qbo_write.py) turns any non-HTTP exception into 500 "QBO API error". A business-rule refusal (6240 duplicate name, 6000-range validation faults, 2000-4999 ValidationException) is the caller's 4xx, and callers string-match the 500 text today.

- In `run_qbo_write`, map the QuickBooks SDK's exceptions by the SDK's own types, the same rule as `_set_active` (#85):
  - the bare `QuickbooksException` (codes 5000-9999) and `ValidationException` (2000-4999) give 400, `detail = f"QBO refused: {e}"`.
  - code 5010 (stale SyncToken) gives 409.
  - code 3001 (throttle) gives 503.
- `AuthorizationException`, `SevereException`, `UnsupportedException`, `GeneralException` and `ObjectNotFoundException` keep today's handling.
- Keep the QBO error text in `detail`, unchanged, after the prefix, so any caller string-matching the code number still sees it.
- Update `_set_active` to use the shared mapping rather than its own copy, if that's a pure deletion.
- Check existing callers that match a 500 from fpqbo write routes before changing it: payouts, fortiumtax, PartnerConnect. Grep ~/projects for `QB Exception`, `status_code == 500`, `QBO API error`. List what you find in the PR body.
- Tests: for each class, a raising service gives the expected status through `run_qbo_write`. A Severe/Auth exception still gives 500. The message text is preserved.

## Docs

CLAUDE.md: the vendor-credits list row notes `doc_number`; the vendor create row notes `Vendor1099`; add a short note on write-route error codes (400 refused, 409 stale SyncToken, 503 throttle).
