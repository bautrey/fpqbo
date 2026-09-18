# FP-QBO — Engineering Constitution

> The rules this codebase is held to, each one written because it was broken first.
> Ensemble's PRD and TRD gates check drafts against these articles.
>
> Last updated: 2026-09-18

This service is the sanctioned route to four live QuickBooks companies. Every
row it returns is somebody's ledger, and every write it makes lands in books an
accountant will reconcile. There is no staging QuickBooks. A sandbox company,
BUR-015, is connected for write testing, though nothing can currently reach it
through the API — see Article I.

Most of what follows is about a single failure shape. This service almost never
crashes. It answers 200 with something wrong, and the caller cannot tell.

---

## Article I — Production QuickBooks is not a test environment

FOR-138, FOR-971, FOR-336 and AUT-691 hold real books. A write against a live
company happens because somebody asked for that specific write.

**The sandbox-first half of this article is NOT YET TRUE OF THIS REPOSITORY,
and it is written knowing that.** No API key resolves BUR-015 — the four keys
in the keychain enumerate only the live companies — so a write cannot currently
be exercised against the sandbox through `/api/*` at all. The one write
endpoint shipped since, #36's vendor-credit delete, was verified against
production FOR-138 with a nonexistent id and a read-only key rather than
against the sandbox. Issuing a sandbox API key is the work that makes this
article true; until then it states the intent and the gap.

Reads against production are fine and are how most claims in this repository
get settled — see Article VII. A read costs an API call against Intuit's quota
and nothing else.

**Not every mistake is recallable.** Six SDK classes carry `VoidMixin` —
Invoice, Payment, BillPayment, SalesReceipt, RecurringInvoice and
RecurringSalesReceipt — and nothing else does. A VendorCredit carries only
`DeleteMixin`, so a credit deleted in error cannot be voided back into
existence, and a credit inside a closed period cannot be removed at all
(#35). Before adding any destructive endpoint, establish what the reverse
operation is, and say plainly in the docstring when there is none.

---

## Article II — A response that claims completeness must have evidence for it

The default failure of this service is a 200 that looks whole and is not.

`/api/attachments/` served exactly 1000 rows with nothing in the response
saying so. A consumer's only available signal was "I got a suspiciously round
number", which is wrong at every other boundary. That was seventeen endpoints
paging and fifteen not, and it was fixed by making the contract uniform rather
than by fixing the worst one (#42).

The true total was unknowable until #42 shipped the header that reports it:
7,468 measured immediately after, and it drifts as attachments are added —
7,472 a few hours later. Quote it with the date or not at all.

**Unknown is an honest answer. Invented completeness is not.** Where the size
of a result set cannot be established, `X-Total-Count` is absent and
`X-Has-More` is true — size unknown, may continue.

**One exception, and it is evidence rather than an escape.** An empty page past
offset 0 proves no row exists at or beyond that offset, so `X-Has-More` is
false there even when the COUNT went unanswered: a complete result set of
unknown size. `_fetch_page`'s `overshot` branch is that case and
`test_an_end_of_set_page_of_unknown_size_says_end_without_saying_size` pins it.
Completeness always rests on something observed — a short page, or an empty one
— never on the absence of contrary information.

**And the evidence has to outrank the assertion.** Five minutes after #42
merged, `/api/reference/exchange-rates` served 1000 rows carrying
`X-Total-Count: 100` and `X-Has-More: false`, because QuickBooks answers
`SELECT COUNT(*) FROM
ExchangeRate` with 100 no matter how many rows the same query returns. A count
below the rows already in hand contradicts data we are holding and is discarded
(#44). Rows observed at `[offset, offset + row_count)` are a fact; a COUNT is a
claim.

---

## Article III — A write is never reported as a success it cannot establish

`existing.delete()` returning `None` does not mean "no response shape". It
means `make_request` hit a Fault the SDK dropped: `handle_exceptions` loops over
`results["Error"]`, so an empty Error list raises nothing and the function falls
off the end. The endpoint answered `200 {"status": "Deleted"}` for a delete
whose outcome was genuinely unknown, which tells an operator reconciling a
correction to stop looking at a credit that may still be in the books (#36).

Three states, and they are not two: it worked, it failed, **we do not know**.
The third gets its own answer, and that answer says which record and says the
outcome is unknown.

**A non-idempotent write is issued once.** `_to_thread_with_retry` is
documented read-paths-only. `DeleteMixin` sends Id and SyncToken, so a retry
after a first attempt that succeeded but whose response was lost comes back as
a refusal, which reads to the caller as a failure that did not happen.

---

## Article IV — QuickBooks' own words reach the caller

A closed period and a linked transaction are ordinary states, not faults, and
the caller has to tell them apart from the response alone. QuickBooks' error
code and message are the part worth reading, so they are passed through rather
than summarised into "QBO API error" (#35).

Pass the response **whole**. An early cut of the vendor-credit delete returned
`deleted.get("VendorCredit") or deleted`, which silently dropped the `time`
field and would drop any key Intuit adds later. A caller can reach into a
response handed over intact; it cannot recover a field discarded on its behalf.

**And quote the string that actually appears.** The SDK maps error codes
2000-4999 to `ValidationException`, rendering "QB Validation Exception"; 6240
falls past that range to the bare class and renders "QB Exception". A downstream
system matching the wrong form never fires on a closed period.

---

## Article V — A green suite is not evidence until you check how it went green

Every guard in this repository is ablated: break the thing it protects, watch
exactly the intended test go red, restore, confirm the suite is green again.
An ablation that was never applied and a healthy guard look identical.

**The ablations that came back GREEN are why this article exists**, and there
have been four in one day:

- Deleting `apply_paging_headers` from a converted router — the thirteen newly
  paged endpoints, spread across eight router files, had no endpoint-level test
  at all, only service-level ones, which never see a header (#42).
- Deleting `order_by=QBO_PAGE_ORDER_BY` from `_query_page` — nothing asserted
  the ORDERBY reached QuickBooks, and stable ordering is the entire premise of
  offset paging.
- Reverting a call site to the hardcoded token lifetime — fourteen tests of the
  new helper all passed, because a helper nothing calls fixes nothing (#43).
- Transposing the two token expiries in the OAuth callback — passed all 1,037
  tests, and would have stored 100 days on the access token so the scheduler
  never refreshed (#43).

Answer a wiring gap by removing the hazard where you can. The transposition was
fixed by deleting the pair, not by testing around it: `apply_token_expiries`
writes both attributes and the call sites hand it the object, so ordering has
one place to be wrong and that place is covered.

**Ablation is blind to a tautology.** An assertion that cannot fail stays green
however the code breaks. Static analysis is the only thing that sees those;
run it on any suite this repository touches.

---

## Article VI — A uniform contract, or a table the caller has to memorise

Seventeen endpoints paged and fifteen did not. The cost was never any single
truncated endpoint — it was that a consumer had to know which was which to know
whether a 200 was the whole answer (#42).

When an endpoint genuinely cannot offer what the others do, it says so rather
than staying silent. `/api/recurring-transactions/` and
`/api/reference/exchange-rates` carry no top-level `Id`, so ordering is
unavailable and an offset would return duplicates forever; they report
`X-Has-More` and no cursor (#20, #42). A cursor that does not work is worse
than no cursor.

`/api/recurring-transactions/` reports `X-Total-Count` as well.
`/api/reference/exchange-rates` does not, and that is the rule above working
rather than an inconsistency: QuickBooks answers COUNT for that entity with 100
however many rows it returns, so the number is discarded and the size is
reported as unknown (#44).

**An exception needs an argument, not a line.**
`/api/bill-payments/by-bill/{id}` is exempt from paging because it returns
exactly the payments the bill's own LinkedTxn names and raises rather than
return a subset — bounded by the bill, not by the ledger.

**Guard the contract mechanically.** A test reads the router table and fails if
any GET under `/api/` returning an array lacks `offset` and is not one of the
named exceptions. A fixture list a human maintains is how the service reached
fifteen unpaged endpoints without a single test objecting.

---

## Article VII — Say what was measured, not what is believed

Claims about QuickBooks get settled against QuickBooks. It is a read and it
costs one API call.

**Reasoning from the SDK source is not measurement.** An adversarial review
raised a CRITICAL that routing `/api/items/` through `where()` would return
`"Sku": null`, because `ListMixin.all()` requests `SELECT *, Sku` and `where()`
does not. The premise — that QuickBooks omits Sku from `*` — was false, and one
production call disproved it: both paths return the same 12 non-empty SKUs. A
docstring in this repository had asserted the same wrong premise and used it to
declare Item unpageable.

**State the extent of what was measured.** FOR-138 is the only connected
company with any Sku set, so that check covers one company and is the only
company capable of producing evidence. Say so rather than generalising.

**Counts are claims too.** "Five call sites" appeared in three commit
messages, three docstrings and a message to another session before anybody
counted. There are four. The count of the wrong counts was itself wrong in the
first draft of this article, which is the joke and also the point.

---

## Article VIII — Tokens rotate, and a lost write costs a reconnect

Intuit rotates the refresh token as part of issuing a new one. **Once
`auth_client.refresh()` has returned**, an exception before the commit does not
degrade the expiry — it can cost that company a reconnect, because the broad
`except` below rolls the transaction back and the token that was stored may no
longer be the live one.

Not every failure in `_refresh_token` is that failure: the credentials check at
the top raises before `refresh()` is ever called, with the stored token
untouched. The dangerous window is specifically between the refresh returning
and the commit landing.

How often a rotation actually invalidates the previous value is not settled
here — Intuit is documented as returning the same refresh token within a
24-hour window, and the scheduler runs every 45 minutes, so the reconnect may
be the exception rather than the rule. The window is treated as dangerous
because the cost when it does bite is a human logging into the admin UI.

Code on that path is written knowing the broad `except` below it rolls back.
`int(float("inf"))` raises OverflowError and an int large enough to convert can
still overflow `timedelta(seconds=...)`; both are caught where the value is
converted rather than allowed to escape (#43).

**Read what Intuit sent.** Every token response states `expires_in` and
`x_refresh_token_expires_in`, and `intuitlib` copies every key of it onto the
client bar `token_type` and `id_token`. Storing a documented default instead is
right by coincidence until the day it is not, and nothing in the service would
notice (#34).

---

## Article IX — The human decides what ships

A clean review loop is a precondition for merging, never permission. Merges
happen on an explicit, per-PR approval, and one approval never carries to the
next PR.

**Deploy green is not verification.** The success signal of a shipped change is
the user-visible reproduction returning the expected output, run within minutes
of the merge. #44 exists because #42's own test plan was run against production
and caught a defect #42 had shipped five minutes earlier; the fix was merged
fifteen minutes after the defect. Tests passing, CI green
and a live deploy are preconditions; the repro is the evidence.

**Report what happened.** If a check was skipped, say which. If a reviewer slot
never answered — CodeRabbit rate-limited, a model reviewer not dispatched
because the diff matched no risky path — say that rather than letting "clean"
imply a roster that did not run.
