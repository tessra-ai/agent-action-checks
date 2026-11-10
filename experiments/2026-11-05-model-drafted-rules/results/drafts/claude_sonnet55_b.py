from datetime import datetime, timedelta

NOW = datetime(2024, 5, 15, 15, 0, 0)
CABINS = ("basic_economy", "economy", "business")
FREE_BAGS = {
    "regular": {"basic_economy": 0, "economy": 1, "business": 2},
    "silver": {"basic_economy": 1, "economy": 2, "business": 3},
    "gold": {"basic_economy": 2, "economy": 3, "business": 4},
}


def _d(x):
    return x if isinstance(x, dict) else {}


def _l(x):
    return x if isinstance(x, list) else []


def _parse_dt(s):
    try:
        return datetime.fromisoformat(str(s))
    except Exception:
        return None


def _num(x):
    try:
        return float(x)
    except Exception:
        return None


def _get_res(db, rid):
    return _d(_d(db.get("reservations")).get(rid))


def _get_user(db, uid):
    return _d(_d(db.get("users")).get(uid))


def _flight_date(db, fn, date):
    return _d(_d(_d(_d(db.get("flights")).get(fn)).get("dates")).get(date))


def _already_flown(db, res):
    for seg in _l(res.get("flights")):
        seg = _d(seg)
        st = _flight_date(db, seg.get("flight_number"), seg.get("date")).get("status")
        if st in ("flying", "landed"):
            return True
    return False


def _any_cancelled_by_airline(db, res):
    for seg in _l(res.get("flights")):
        seg = _d(seg)
        st = _flight_date(db, seg.get("flight_number"), seg.get("date")).get("status")
        if st == "cancelled":
            return True
    return False


def _any_delayed(db, res):
    for seg in _l(res.get("flights")):
        seg = _d(seg)
        st = _flight_date(db, seg.get("flight_number"), seg.get("date")).get("status")
        if st == "delayed":
            return True
    return False


def _owner_ok(ctx, uid, out, rid=None):
    # Policy: "The agent must first obtain the user id from the user."
    if uid is None:
        return
    typed = ctx.typed_user_ids
    if typed is not None and uid not in typed:
        out.append(("USER_ID_NOT_PROVIDED",
                    "User id %s was not typed by the customer." % uid))


def _check_reservation_owner(ctx, res, out):
    # Policy: user must provide their user id; the reservation must belong to that user.
    owner = res.get("user_id")
    typed = ctx.typed_user_ids
    if owner is not None and typed is not None and owner not in typed:
        out.append(("RESERVATION_OWNER_MISMATCH",
                    "Reservation belongs to %s, who was not identified by the customer." % owner))


def _payment_ok(user, pid, out, rule, need_single_gift_or_card=False):
    pm = _d(_d(user.get("payment_methods")).get(pid))
    if not pm:
        # Policy: "All payment methods must already be in user profile for safety reasons."
        out.append((rule, "Payment method %s is not in the user's profile." % pid))
        return None
    if need_single_gift_or_card and pm.get("source") not in ("gift_card", "credit_card"):
        # Policy: user needs to provide a single gift card or credit card for payment/refund.
        out.append((rule, "Payment method %s must be a gift card or credit card." % pid))
    return pm


def _check_book(ctx, out):
    a = _d(ctx.args)
    db = ctx.db
    uid = a.get("user_id")
    user = _get_user(db, uid)
    _owner_ok(ctx, uid, out)
    if uid is not None and not user:
        out.append(("BOOK_USER_UNKNOWN", "User %s not found." % uid))

    passengers = _l(a.get("passengers"))
    # Policy: "Each reservation can have at most five passengers."
    if len(passengers) > 5:
        out.append(("BOOK_MAX_PASSENGERS", "More than five passengers."))
    if len(passengers) == 0:
        out.append(("BOOK_MAX_PASSENGERS", "No passengers on the reservation."))

    cabin = a.get("cabin")
    if cabin not in CABINS:
        out.append(("BOOK_CABIN_INVALID", "Unknown cabin %r." % (cabin,)))

    flights = _l(a.get("flights"))
    # Round trip / one way shape: the trip type must be consistent with the flights.
    ftype = a.get("flight_type")
    if ftype == "one_way" and len(flights) > 2:
        pass  # connections allowed; do not block

    total = 0.0
    price_known = True
    for seg in flights:
        seg = _d(seg)
        fd = _flight_date(db, seg.get("flight_number"), seg.get("date"))
        st = fd.get("status")
        if not fd:
            out.append(("BOOK_FLIGHT_NOT_FOUND",
                        "Flight %s on %s not found." % (seg.get("flight_number"), seg.get("date"))))
            price_known = False
            continue
        # Policy: only flights with status 'available' can be booked.
        if st != "available":
            out.append(("BOOK_FLIGHT_NOT_AVAILABLE",
                        "Flight %s on %s has status %s; only available flights can be booked."
                        % (seg.get("flight_number"), seg.get("date"), st)))
            price_known = False
            continue
        seats = _d(fd.get("available_seats")).get(cabin)
        if isinstance(seats, (int, float)) and seats < len(passengers):
            out.append(("BOOK_NO_SEATS",
                        "Only %s %s seats on %s %s for %d passengers."
                        % (seats, cabin, seg.get("flight_number"), seg.get("date"), len(passengers))))
        p = _num(_d(fd.get("prices")).get(cabin))
        if p is None:
            price_known = False
        else:
            total += p * len(passengers)

    # Payment rules.
    pays = _l(a.get("payment_methods"))
    n_cert = n_card = n_gift = 0
    pay_sum = 0.0
    pay_sum_known = True
    seen = {}
    for p in pays:
        p = _d(p)
        pid = p.get("payment_id")
        amt = _num(p.get("amount"))
        pm = _d(_d(user.get("payment_methods")).get(pid))
        if user:
            if not pm:
                # Policy: payment methods must already be in user profile.
                out.append(("BOOK_PAYMENT_NOT_IN_PROFILE",
                            "Payment method %s not in user profile." % pid))
        src = pm.get("source")
        if src == "certificate":
            n_cert += 1
        elif src == "credit_card":
            n_card += 1
        elif src == "gift_card":
            n_gift += 1
        if amt is None:
            pay_sum_known = False
        else:
            pay_sum += amt
            seen[pid] = seen.get(pid, 0.0) + amt
        if pid in seen and amt is not None and pm and src in ("gift_card", "certificate"):
            bal = _num(pm.get("amount"))
            if bal is not None and seen[pid] > bal + 1e-9:
                # Policy: a gift card / certificate cannot be charged beyond its balance.
                out.append(("BOOK_PAYMENT_INSUFFICIENT_BALANCE",
                            "Payment method %s balance %.2f is less than amount %.2f."
                            % (pid, bal, seen[pid])))
    # Policy: at most one travel certificate, one credit card, three gift cards.
    if n_cert > 1:
        out.append(("BOOK_PAYMENT_LIMITS", "More than one travel certificate."))
    if n_card > 1:
        out.append(("BOOK_PAYMENT_LIMITS", "More than one credit card."))
    if n_gift > 3:
        out.append(("BOOK_PAYMENT_LIMITS", "More than three gift cards."))
    if len(set(_d(p).get("payment_id") for p in pays)) < len(pays):
        out.append(("BOOK_PAYMENT_LIMITS", "Same payment method listed more than once."))

    # Baggage.
    tb = a.get("total_baggages")
    nb = a.get("nonfree_baggages")
    membership = user.get("membership")
    if isinstance(tb, int) and isinstance(nb, int) and membership in FREE_BAGS and cabin in CABINS:
        free = FREE_BAGS[membership][cabin] * len(passengers)
        # Policy: free allowance by membership and cabin; each extra bag is $50.
        expected_nonfree = max(0, tb - free)
        if nb != expected_nonfree:
            out.append(("BOOK_BAGGAGE_COUNT",
                        "nonfree_baggages=%s but allowance implies %s (total %s, free %s)."
                        % (nb, expected_nonfree, tb, free)))
    if isinstance(nb, int) and isinstance(tb, int) and (nb < 0 or nb > tb):
        out.append(("BOOK_BAGGAGE_COUNT", "Inconsistent baggage counts."))

    # Price vs payment.
    if price_known and pay_sum_known and cabin in CABINS and isinstance(nb, int):
        total_price = total
        if a.get("insurance") == "yes":
            total_price += 30.0 * len(passengers)
        total_price += 50.0 * nb
        if abs(total_price - pay_sum) > 0.01:
            out.append(("BOOK_PAYMENT_TOTAL",
                        "Payments sum to %.2f but the booking costs %.2f." % (pay_sum, total_price)))


def _check_cancel(ctx, out):
    a = _d(ctx.args)
    db = ctx.db
    rid = a.get("reservation_id")
    res = _get_res(db, rid)
    if not res:
        return
    _check_reservation_owner(ctx, res, out)
    if res.get("status") == "cancelled":
        out.append(("CANCEL_ALREADY_CANCELLED", "Reservation already cancelled."))
        return
    # Policy: "If any portion of the flight has already been flown, the agent cannot help."
    if _already_flown(db, res):
        out.append(("CANCEL_ALREADY_FLOWN",
                    "A segment has already been flown (or is in flight); cancellation not allowed."))
        return
    # Policy: cancellable if booked within 24h, airline cancelled, business, or insured (reason-dependent).
    created = _parse_dt(res.get("created_at"))
    within_24h = False
    if created is not None:
        delta = NOW - created
        within_24h = timedelta(0) <= delta <= timedelta(hours=24) or (delta < timedelta(0))
    airline_cancelled = _any_cancelled_by_airline(db, res)
    business = res.get("cabin") == "business"
    insured = res.get("insurance") == "yes"
    if not (within_24h or airline_cancelled or business or insured):
        out.append(("CANCEL_NOT_ELIGIBLE",
                    "Not booked in the last 24h, no airline cancellation, not business, no insurance."))


def _check_update_flights(ctx, out):
    a = _d(ctx.args)
    db = ctx.db
    rid = a.get("reservation_id")
    res = _get_res(db, rid)
    if not res:
        return
    _check_reservation_owner(ctx, res, out)
    user = _get_user(db, res.get("user_id"))
    if res.get("status") == "cancelled":
        out.append(("MODIFY_CANCELLED_RESERVATION", "Reservation is cancelled."))

    new_cabin = a.get("cabin")
    old_cabin = res.get("cabin")
    old_flights = [_d(f) for f in _l(res.get("flights"))]
    new_flights = [_d(f) for f in _l(a.get("flights"))]

    def key(f):
        return (f.get("flight_number"), f.get("date"))

    flights_same = [key(f) for f in old_flights] == [key(f) for f in new_flights]

    if new_cabin not in CABINS:
        out.append(("MODIFY_CABIN_INVALID", "Unknown cabin %r." % (new_cabin,)))

    # Policy: "Basic economy flights cannot be modified." (changing flights; cabin change alone is allowed)
    if old_cabin == "basic_economy" and not flights_same:
        out.append(("MODIFY_BASIC_ECONOMY",
                    "Basic economy reservations cannot have their flights changed."))

    # Policy: "Cabin cannot be changed if any flight in the reservation has already been flown."
    if new_cabin != old_cabin and _already_flown(db, res):
        out.append(("MODIFY_CABIN_AFTER_FLOWN",
                    "Cabin cannot be changed once any segment has been flown."))

    # Policy: flights can be changed without changing origin, destination, and trip type.
    if not flights_same:
        if _already_flown(db, res):
            # Flown segments cannot be replaced; only block if a flown segment is altered.
            for i, of in enumerate(old_flights):
                st = _flight_date(db, of.get("flight_number"), of.get("date")).get("status")
                if st in ("landed", "flying"):
                    if key(of) not in [key(f) for f in new_flights]:
                        out.append(("MODIFY_FLOWN_SEGMENT",
                                    "Segment %s on %s has already been flown and cannot be changed."
                                    % key(of)))
        if new_flights and old_flights:
            if _d(new_flights[0]).get("origin") is not None:
                pass
            # Compare end points using the flights database.
            def endpoints(fl):
                if not fl:
                    return None, None
                first = _d(_d(db.get("flights")).get(fl[0].get("flight_number")))
                last = _d(_d(db.get("flights")).get(fl[-1].get("flight_number")))
                return first.get("origin"), last.get("destination")
            o_old = res.get("origin")
            d_old = res.get("destination")
            o_new, d_new = endpoints(new_flights)
            if res.get("flight_type") == "round_trip":
                # Round trip: first origin must equal the old origin and the last destination
                # must be the old origin again (returns home).
                first = _d(_d(db.get("flights")).get(new_flights[0].get("flight_number")))
                last = _d(_d(db.get("flights")).get(new_flights[-1].get("flight_number")))
                if first.get("origin") is not None and first.get("origin") != o_old:
                    out.append(("MODIFY_ORIGIN_DEST",
                                "Origin changed from %s to %s." % (o_old, first.get("origin"))))
                if last.get("destination") is not None and last.get("destination") != o_old:
                    out.append(("MODIFY_ORIGIN_DEST",
                                "Round trip must still end at %s." % o_old))
            else:
                if o_new is not None and o_old is not None and o_new != o_old:
                    out.append(("MODIFY_ORIGIN_DEST",
                                "Origin changed from %s to %s." % (o_old, o_new)))
                if d_new is not None and d_old is not None and d_new != d_old:
                    out.append(("MODIFY_ORIGIN_DEST",
                                "Destination changed from %s to %s." % (d_old, d_new)))
        if len(new_flights) != len(old_flights):
            out.append(("MODIFY_TRIP_TYPE",
                        "Number of segments changed (%d -> %d); trip type must stay the same."
                        % (len(old_flights), len(new_flights))))

    # Flight availability for new segments.
    npass = len(_l(res.get("passengers")))
    old_keys = set((key(f), old_cabin) for f in old_flights)
    new_cost = 0.0
    cost_known = True
    for f in new_flights:
        fd = _flight_date(db, f.get("flight_number"), f.get("date"))
        kept = (key(f), new_cabin) in old_keys
        if not fd:
            out.append(("MODIFY_FLIGHT_NOT_FOUND",
                        "Flight %s on %s not found." % key(f)))
            cost_known = False
            continue
        if not kept and fd.get("status") != "available":
            out.append(("MODIFY_FLIGHT_NOT_AVAILABLE",
                        "Flight %s on %s has status %s; cannot be booked."
                        % (key(f) + (fd.get("status"),))))
            cost_known = False
            continue
        if not kept:
            seats = _d(fd.get("available_seats")).get(new_cabin)
            if isinstance(seats, (int, float)) and seats < npass:
                out.append(("MODIFY_NO_SEATS",
                            "Only %s %s seats left on %s %s." % (seats, new_cabin, f.get("flight_number"), f.get("date"))))
            p = _num(_d(fd.get("prices")).get(new_cabin))
            if p is None:
                cost_known = False
            else:
                new_cost += p * npass
        else:
            old_price = None
            for of in old_flights:
                if key(of) == key(f):
                    old_price = _num(of.get("price"))
            if old_price is None:
                cost_known = False
            else:
                new_cost += old_price * npass

    # Payment method.
    pid = a.get("payment_id")
    pm = _payment_ok(user, pid, out, "MODIFY_PAYMENT_METHOD", need_single_gift_or_card=True) if user else None

    # Gift card balance for any extra charge.
    if pm and cost_known and pm.get("source") == "gift_card":
        old_total = 0.0
        ok = True
        for of in old_flights:
            p = _num(of.get("price"))
            if p is None:
                ok = False
            else:
                old_total += p * npass
        if ok:
            diff = new_cost - old_total
            bal = _num(pm.get("amount"))
            if diff > 0 and bal is not None and diff > bal + 1e-9:
                out.append(("MODIFY_PAYMENT_INSUFFICIENT_BALANCE",
                            "Price difference %.2f exceeds gift card balance %.2f." % (diff, bal)))


def _check_update_baggages(ctx, out):
    a = _d(ctx.args)
    db = ctx.db
    rid = a.get("reservation_id")
    res = _get_res(db, rid)
    if not res:
        return
    _check_reservation_owner(ctx, res, out)
    user = _get_user(db, res.get("user_id"))
    if res.get("status") == "cancelled":
        out.append(("BAGS_CANCELLED_RESERVATION", "Reservation is cancelled."))

    tb = a.get("total_baggages")
    nb = a.get("nonfree_baggages")
    old_tb = res.get("total_baggages")
    old_nb = res.get("nonfree_baggages")
    # Policy: "The user can add but not remove checked bags."
    if isinstance(tb, int) and isinstance(old_tb, int) and tb < old_tb:
        out.append(("BAGS_REMOVE", "Total bags would drop from %s to %s." % (old_tb, tb)))
    if isinstance(nb, int) and isinstance(old_nb, int) and nb < old_nb:
        out.append(("BAGS_REMOVE", "Non-free bags would drop from %s to %s." % (old_nb, nb)))

    # Policy: free allowance depends on membership and cabin; each extra bag is $50.
    membership = user.get("membership")
    cabin = res.get("cabin")
    npass = len(_l(res.get("passengers")))
    if isinstance(tb, int) and isinstance(nb, int) and membership in FREE_BAGS and cabin in CABINS:
        free = FREE_BAGS[membership][cabin] * npass
        expected = max(0, tb - free)
        if nb != expected:
            out.append(("BAGS_COUNT",
                        "nonfree_baggages=%s but allowance implies %s (total %s, free %s)."
                        % (nb, expected, tb, free)))
    if isinstance(tb, int) and isinstance(nb, int) and (nb < 0 or nb > tb):
        out.append(("BAGS_COUNT", "Inconsistent baggage counts."))

    pid = a.get("payment_id")
    pm = _payment_ok(user, pid, out, "BAGS_PAYMENT_METHOD") if user else None
    if pm and isinstance(nb, int) and isinstance(old_nb, int):
        charge = 50.0 * max(0, nb - old_nb)
        if pm.get("source") in ("gift_card", "certificate"):
            bal = _num(pm.get("amount"))
            if bal is not None and charge > bal + 1e-9:
                out.append(("BAGS_PAYMENT_INSUFFICIENT_BALANCE",
                            "Charge %.2f exceeds balance %.2f of %s." % (charge, bal, pid)))


def _check_update_passengers(ctx, out):
    a = _d(ctx.args)
    db = ctx.db
    rid = a.get("reservation_id")
    res = _get_res(db, rid)
    if not res:
        return
    _check_reservation_owner(ctx, res, out)
    if res.get("status") == "cancelled":
        out.append(("PAX_CANCELLED_RESERVATION", "Reservation is cancelled."))
    new = _l(a.get("passengers"))
    old = _l(res.get("passengers"))
    # Policy: "The user can modify passengers but cannot modify the number of passengers."
    if len(new) != len(old):
        out.append(("PAX_COUNT_CHANGE",
                    "Passenger count would change from %d to %d." % (len(old), len(new))))


def _check_certificate(ctx, out):
    a = _d(ctx.args)
    db = ctx.db
    uid = a.get("user_id")
    user = _get_user(db, uid)
    _owner_ok(ctx, uid, out)
    amount = _num(a.get("amount"))
    if not user:
        return

    # Policy: "Do not offer compensation for any other reason than the ones listed above."
    # Policy: only silver/gold members, or insured, or business passengers qualify.
    membership = user.get("membership")
    candidates = []
    for rid in _l(user.get("reservations")):
        res = _get_res(db, rid)
        if not res:
            continue
        candidates.append(res)

    def eligible(res):
        return (membership in ("silver", "gold")
                or res.get("insurance") == "yes"
                or res.get("cabin") == "business")

    # Compensation can only be given for cancelled or delayed flights in one of the user's reservations.
    amounts_allowed = set()
    any_reason = False
    for res in candidates:
        npass = len(_l(res.get("passengers")))
        if not eligible(res):
            continue
        if _any_cancelled_by_airline(db, res):
            any_reason = True
            amounts_allowed.add(100.0 * npass)
        if _any_delayed(db, res):
            any_reason = True
            amounts_allowed.add(50.0 * npass)

    if not any_reason:
        out.append(("COMP_NOT_ELIGIBLE",
                    "No cancelled/delayed flight in an eligible reservation of this user."))
        return
    if amount is not None and amounts_allowed and not any(abs(amount - x) < 0.01 for x in amounts_allowed):
        out.append(("COMP_AMOUNT",
                    "Amount %.2f does not match $100/passenger (cancelled) or $50/passenger (delayed); "
                    "allowed: %s." % (amount, sorted(amounts_allowed))))

    # Policy: delay compensation is only after the reservation was changed or cancelled.
    # If the only basis is a delay (no cancelled flight), require a prior change/cancel write.
    only_delay = True
    for res in candidates:
        if eligible(res) and _any_cancelled_by_airline(db, res):
            only_delay = False
    if only_delay and amount is not None:
        done = False
        for name, args in ctx.prior_writes or ():
            if name in ("cancel_reservation", "update_reservation_flights"):
                done = True
        if not done:
            out.append(("COMP_DELAY_NEEDS_CHANGE",
                        "Delay compensation requires the reservation to be changed or cancelled first."))

    # No duplicate compensation within the conversation for the same amount.
    for name, args in ctx.prior_writes or ():
        if name == "send_certificate" and _d(args).get("user_id") == uid:
            if amount is not None and _num(_d(args).get("amount")) == amount:
                out.append(("COMP_DUPLICATE", "An identical certificate was already sent."))
                break


def check(ctx):
    out = []
    try:
        action = ctx.action
        if action == "book_reservation":
            _check_book(ctx, out)
        elif action == "cancel_reservation":
            _check_cancel(ctx, out)
        elif action == "update_reservation_flights":
            _check_update_flights(ctx, out)
        elif action == "update_reservation_baggages":
            _check_update_baggages(ctx, out)
        elif action == "update_reservation_passengers":
            _check_update_passengers(ctx, out)
        elif action == "send_certificate":
            _check_certificate(ctx, out)
    except Exception:
        pass
    return out
