"""Service-layer exceptions that name the condition they mean.

Every one of the ~79 router handlers in this service ends the same way:

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")

`ValueError` is the record-not-found channel, because `qbo_service` raises it
for "QBO company not found" and "Bill not found". The problem is that it also
raises `ValueError` for three conditions that are not a missing record at all:
credentials that are not configured, a token refresh that failed, and a
company whose authorization has been revoked. All three come back to the
caller as `404 not found`.

That is not a cosmetic mislabel. A sync job or monitor routing on the status
code records "this company does not exist" and moves on, when the truth is
"our credentials are broken and every request will fail until someone
reconnects". The two need different reactions and the caller cannot tell them
apart.

The classes here follow `QboQueryError` in `app/utils/qbo_query.py`, added for
exactly this reason in #14: name the condition in the type so no handler has
to infer it from a message. They differ from it in one respect — they subclass
`HTTPException` rather than `Exception`.

That is deliberate and it is a trade. A plain `Exception` subclass would be
caught by each handler's blanket `except Exception` and rewrapped as a 500
before any app-level handler could see it, so carrying the status on the
exception is what lets the intent survive the handlers as they are today.
`QboQueryError` makes the opposite choice for a good reason: it means "a
programmer built a bad query", which has no business being anything but a 500,
and staying outside the `ValueError`/`TypeError` hierarchy is what guarantees
no 404 handler can swallow it.

The `except HTTPException: raise` guard is what carries these through. It is
present, and first, on every router handler that can receive one — meaning
every handler reached through QBOService. It is deliberately NOT added to
`auth.py` or `qbo_oauth.py`: neither calls QBOService, so neither can see
these types, and neither imports HTTPException, so a guard naming it there
would raise NameError while handling an error and take the recovery path
down with it. Catch-alls elsewhere in the app (database.py, main.py,
qbo_service.py, token_refresh_scheduler.py) are outside the request path and
unaffected.
"""

from fastapi import HTTPException

__all__ = [
    "QboCompanyDisconnected",
    "QboNotFound",
    "QboUnavailable",
]


class QboNotFound(HTTPException):
    """A record the caller named does not exist.

    The genuine 404: a company code with no row, a bill id QBO does not know.
    Not for a company that exists but cannot currently be reached — that is
    `QboUnavailable` or `QboCompanyDisconnected`.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(status_code=404, detail=detail)


class QboCompanyDisconnected(HTTPException):
    """The company exists, but its QuickBooks authorization is gone.

    409 rather than 404 because the record is present and the caller's request
    is well formed; what is wrong is the state of the connection, and a human
    can fix it by reconnecting. Answering 404 here tells a monitor the company
    was deleted.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(status_code=409, detail=detail)


class QboUnavailable(HTTPException):
    """This service cannot reach QuickBooks for this company right now.

    Covers credentials that are not configured and a token refresh that
    failed. 503 because it is our side that is broken and the caller has no
    request they could have made instead — the honest reading is "unavailable,
    try later or escalate", not "no such thing".

    A failed refresh sits here rather than under ``QboCompanyDisconnected``
    because the failure is caught with a bare ``except Exception``: a network
    timeout and a genuinely dead grant arrive identically, and answering 409
    would page someone to re-authorise a company that is fine. Splitting them
    needs the transient classifier at the raise site.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(status_code=503, detail=detail)
