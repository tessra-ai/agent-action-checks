```python
from datetime import datetime, timedelta

NOW = datetime(2024, 5, 15, 15, 0, 0)
TODAY = "2024-05-15"
ALLOW = {
    "regular": {"basic_economy": 0, "economy": 1, "business": 2},
    "silver": {"basic_economy": 1, "economy": 2, "business": 3},
    "gold": {"basic_economy": 2, "economy": 3, "business": 4},
}
CABINS = ("basic_economy", "economy", "business")


def _d(x):
    return x if isinstance(x, dict) else {}


def _l(x):
    return x if isinstance(x, list) else []


def _num(x):
    try:
        if isinstance(x, bool):
            return None
        return float(x)
    except Exception:
        return None


def _flight_date(db, fn, date):
    return _d(_d(_d(_d(db).get("flights")).get(fn)).get("dates")).get(date)


def _status(db, fn, date):
    rec = _flight_date(db, fn, date)
    if isinstance(rec, dict):
        return rec.get("status")
    return None


def _price(db, fn, date, cabin):
    rec = _flight_date(db, fn, date)
    if not isinstance(rec, dict) or rec.get("status") != "available":
        return None
    return _num(_d(rec.get("prices")).get(cabin))


def _seats(db, fn, date, cabin):
    rec = _flight_date(db, fn, date)
    if not isinstance(rec, dict) or rec.get("status") != "available":
        return None
    return _num(_d(rec.get("available_seats")).get(cabin))


def _is_flown(db, fn, date):
    st = _status(db, fn, date)
    if st in ("landed", "flying"):
        return True
    if st is None and isinstance(date, str) and date < TODAY:
        return True
    return False


def _res_flown(db, res):
    for f in _l(res.get("flights")):
        f = _d(f)
        if _is_flown(db, f.get("flight_number"), f.get("date")):
            return True
    return False


def _parse_dt(s):
    try:
        return datetime.fromisoformat(str(s))
    except Exception:
        return None


def _allowance(db, user_id, cabin):
    user = _d(_d(db.get("users")).get(user_id))
    m = user.get("membership")
    return _d(ALLOW.get(m)).get(cabin)


def _pm(db, user_id, pid):
    user = _d(_d(db.get("users")).get(user_id))
    return _d(user.get("payment_methods")).get(pid)


def _typed(ctx, user_id, out):
    # Policy: "The agent must first obtain the user id from the user."
    try:
        if user_id and user_id not in ctx.typed_user_ids:
            out.append(("USER_ID_NOT_PROVIDED",
                        "User id %s was not typed by the customer" % user_id))
    except Exception:
        pass


def _book(ctx, out):
    db, a = ctx.db, _d(ctx.args)
    uid = a.get("user_id")
    _typed(ctx, uid, out)
    user = _d(_d(db.get("users")).get(uid))
    cabin = a.get("cabin")
    pax = _l(a.get("passengers"))
    n = len(pax)
    flights = _l(a.get("flights"))

    # Policy: "Each reservation can have at most five passengers."
    if n > 5 or n < 1:
        out.append(("BOOK_PASSENGER_COUNT", "Passenger count %d not in 1..5" % n))

    # Policy: cabin classes are basic economy / economy / business.
    if cabin not in CABINS:
        out.append(("BOOK_CABIN_INVALID", "Unknown cabin %r" % (cabin,)))

    # Policy: only flights with status available can be booked (seats must exist).
    total = 0.0
    total_ok = cabin in CABINS
    for f in flights:
        f = _d(f)
        fn, dt = f.get("flight_number"), f.get("date")
        st = _status(db, fn, dt)
        if st != "available":
            out.append(("BOOK_FLIGHT_NOT_AVAILABLE",
                        "%s on %s has status %s" % (fn, dt, st)))
            total_ok = False
            continue
        if cabin in CABINS:
            seats = _seats(db, fn, dt, cabin)
            if seats is not None and seats < n:
                out.append(("BOOK_NO_SEATS",
                            "%s on %s has %s %s seats for %d passengers" % (fn, dt, seats, cabin, n)))
            p = _price(db, fn, dt, cabin)
            if p is None:
                total_ok = False
            else:
                total += p * n

    if a.get("insurance") not in ("yes", "no"):
        out.append(("BOOK_INSURANCE_INVALID", "Insurance must be yes or no"))

    # Policy: free bag allowance by membership/cabin; each extra bag is $50.
    tb, nb = _num(a.get("total_baggages")), _num(a.get("nonfree_baggages"))
    allow = _allowance(db, uid, cabin)
    if tb is not None and nb is not None and allow is not None:
        expected = max(0, tb - allow * n)
        if abs(nb - expected) > 1e-9:
            out.append(("BOOK_BAGGAGE_COUNT",
                        "nonfree_baggages %s but allowance implies %s" % (nb, expected)))
    elif tb is not None and nb is not None and nb > tb:
        out.append(("BOOK_BAGGAGE_COUNT", "nonfree bags exceed total bags"))

    # Policy: at most one travel certificate, one credit card, three gift cards;
    # payment methods must be in the user's profile.
    pays = _l(a.get("payment_methods"))
    counts = {"certificate": 0, "credit_card": 0, "gift_card": 0}
    seen = set()
    paysum = 0.0
    paysum_ok = True
    for p in pays:
        p = _d(p)
        pid = p.get("payment_id")
        amt = _num(p.get("amount"))
        if amt is None:
            paysum_ok = False
        else:
            paysum += amt
        if pid in seen:
            out.append(("BOOK_PAYMENT_DUPLICATE", "Payment method %s used twice" % pid))
        seen.add(pid)
        pm = _pm(db, uid, pid)
        if not isinstance(pm, dict):
            if user:
                out.append(("BOOK_PAYMENT_NOT_IN_PROFILE",
                            "Payment method %s not in user profile" % pid))
            continue
        src = pm.get("source")
        if src in counts:
            counts[src] += 1
        if src in ("gift_card", "certificate") and amt is not None:
            bal = _num(pm.get("amount"))
            if bal is not None and amt > bal + 1e-9:
                out.append(("BOOK_PAYMENT_INSUFFICIENT",
                            "%s balance %s less than charge %s" % (pid, bal, amt)))
    if counts["certificate"] > 1:
        out.append(("BOOK_PAYMENT_LIMIT", "More than one travel certificate"))
    if counts["credit_card"] > 1:
        out.append(("BOOK_PAYMENT_LIMIT", "More than one credit card"))
    if counts["gift_card"] > 3:
        out.append(("BOOK_PAYMENT_LIMIT", "More than three gift cards"))

    # Booking price must equal payment total.
    if total_ok and paysum_ok and nb is not None and a.get("insurance") in ("yes", "no"):
        price = total + (30 * n if a.get("insurance") == "yes" else 0) + 50 * nb
        if abs(price - paysum) > 0.01:
            out.append(("BOOK_PAYMENT_TOTAL",
                        "Payments sum %s but price is %s" % (paysum, price)))


def _cancel(ctx, out):
    db, a = ctx.db, _d(ctx.args)
    res = _d(_d(db.get("reservations")).get(a.get("reservation_id")))
    if not res:
        return
    _typed(ctx, res.get("user_id"), out)

    # Policy: "If any portion of the flight has already been flown, the agent cannot help."
    if _res_flown(db, res):
        out.append(("CANCEL_ALREADY_FLOWN", "Part of the reservation has been flown"))
        return

    # Policy: cancellable if booked within 24h, airline cancelled, business,
    # or insured (reason cannot be judged from records).
    created = _parse_dt(res.get("created_at"))
    recent = created is not None and (NOW - created) <= timedelta(hours=24)
    airline_cancelled = any(
        _status(db, _d(f).get("flight_number"), _d(f).get("date")) == "cancelled"
        for f in _l(res.get("flights")))
    business = res.get("cabin") == "business"
    insured = res.get("insurance") == "yes"
    if not (recent or airline_cancelled or business or insured):
        out.append(("CANCEL_NOT_ELIGIBLE",
                    "Not booked in last 24h, no airline-cancelled flight, not business, no insurance"))


def _update_flights(ctx, out):
    db, a = ctx.db, _d(ctx.args)
    res = _d(_d(db.get("reservations")).get(a.get("reservation_id")))
    if not res:
        return
    uid = res.get("user_id")
    _typed(ctx, uid, out)
    cabin = a.get("cabin")
    old_cabin = res.get("cabin")
    old
