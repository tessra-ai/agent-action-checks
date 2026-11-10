```python
import datetime

CURRENT_TIME = datetime.datetime(2024, 5, 15, 15, 0, 0)


def get_user(ctx, user_id):
    try:
        return ctx.db["users"][user_id]
    except Exception:
        return None


def get_reservation(ctx, reservation_id):
    try:
        return ctx.db["reservations"][reservation_id]
    except Exception:
        return None


def get_flight(ctx, flight_number):
    try:
        return ctx.db["flights"][flight_number]
    except Exception:
        return None


def parse_datetime(s):
    # Parses both "YYYY-MM-DDTHH:MM:SS" and "YYYY-MM-DD HH:MM:SS"
    # and also "YYYY-MM-DD"
    if not isinstance(s, str):
        return None
    try:
        if "T" in s:
            return datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")
        elif len(s) == 10:
            return datetime.datetime.strptime(s, "%Y-%m-%d")
        else:
            return datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def date_difference_hours(dt1, dt2):
    if not dt1 or not dt2:
        return None
    delta = dt1 - dt2
    return delta.total_seconds() / 3600


def all_flights_unflown(reservation, ctx):
    """Return True iff all flights have not yet departed (status not landed/flying)."""
    for segment in reservation.get("flights", []):
        flight = get_flight(ctx, segment.get("flight_number"))
        if not flight:
            continue
        flight_date = segment.get("date")
        flight_dates = flight.get("dates", {})
        this_date = flight_dates.get(flight_date, {})
        status = this_date.get("status")
        if status in ("landed", "flying"):
            return False
    return True


def any_flight_flown(reservation, ctx):
    """Return True if any flight in the reservation has already flown."""
    for segment in reservation.get("flights", []):
        flight = get_flight(ctx, segment.get("flight_number"))
        if not flight:
            continue
        flight_date = segment.get("date")
        flight_dates = flight.get("dates", {})
        this_date = flight_dates.get(flight_date, {})
        status = this_date.get("status")
        if status in ("landed", "flying"):
            return True
    return False


def any_flight_cancelled(reservation, ctx):
    """Returns True iff at least one segment is cancelled by airline."""
    for segment in reservation.get("flights", []):
        flight = get_flight(ctx, segment.get("flight_number"))
        if not flight:
            continue
        flight_date = segment.get("date")
        flight_dates = flight.get("dates", {})
        date_info = flight_dates.get(flight_date, {})
        status = date_info.get("status", "").lower()
        if status == "cancelled":
            return True
    return False


def all_segments_basic_economy(reservation):
    cabin = reservation.get('cabin')
    return cabin == 'basic_economy'


def user_has_payment_method(user, payment_id):
    try:
        return payment_id in user.get("payment_methods", {})
    except Exception:
        return False


def is_reason_covered_by_insurance(insurance, reason):
    # Policy: insurance covers health and weather.
    if not insurance or insurance != "yes":
        return False
    allowed = {"health", "weather", "illness", "medical", "bad weather"}
    lower = str(reason or "").lower()
    return any(word in lower for word in allowed)


def sum_payments(payment_methods):
    try:
        return sum(float(m.get("amount", 0)) for m in payment_methods or [])
    except Exception:
        return 0.0


def get_membership(user):
    return (user or {}).get("membership")


def calculate_free_bags(membership, cabin):
    # Policy: checked bag allowance
    bag_table = {
        "regular": {"basic_economy": 0, "economy": 1, "business": 2},
        "silver": {"basic_economy": 1, "economy": 2, "business": 3},
        "gold": {"basic_economy": 2, "economy": 3, "business": 4},
    }
    return bag_table.get(membership, {}).get(cabin, 0)


def get_passenger_count(passenger_list):
    try:
        return len(passenger_list or [])
    except Exception:
        return 0


def str_equal(a, b):
    return str(a or "").strip().lower() == str(b or "").strip().lower()

def get_userid_from_reservation(ctx, reservation_id):
    res = get_reservation(ctx, reservation_id)
    if res:
        return res.get("user_id")
    return None


def check(ctx):
    broken = []
    action = getattr(ctx, "action", None)
    args = getattr(ctx, "args", {})
    db = getattr(ctx, "db", {})
    typed_user_ids = getattr(ctx, "typed_user_ids", frozenset())

    # --- Policy checks per tool ---

    # Book reservation
    if action == "book_reservation":
        # Get user from user_id
        user_id = args.get("user_id")
        user = get_user(ctx, user_id)
        passengers = args.get("passengers", [])
        total_baggages = args.get("total_baggages", 0)
        nonfree_baggages = args.get("nonfree_baggages", 0)
        payment_methods = args.get("payment_methods", [])
        flights = args.get("flights", [])
        cabin = args.get("cabin")
        insurance = args.get("insurance", None)
        flight_type = args.get("flight_type")

        # BOOK_USERID
        # "The agent must first obtain the user id from the user."
        if user_id not in typed_user_ids:
            broken.append(("BOOK_USERID", "User id not explicitly provided by the customer."))

        # BOOK_PASSENGER_LIMIT
        # "Each reservation can have at most five passengers."
        if get_passenger_count(passengers) > 5:
            broken.append(("BOOK_PASSENGER_LIMIT", "Maximum 5 passengers per reservation."))

        # BOOK_PAYMENT_SRC
        # "All payment methods must already be in user profile for safety reasons."
        for pm in payment_methods:
            pid = pm.get("payment_id")
            if not (user and user_has_payment_method(user, pid)):
                broken.append(("BOOK_PAYMENT_SRC", "All payment methods must be on user profile."))

        # BOOK_PAYMENT_TYPE_LIMIT
        # - Each reservation can use at most one travel certificate, at most one credit card, and at most three gift cards.
        cert_count = sum(1 for pm in payment_methods if pm.get("payment_id", "").startswith("certificate_"))
        cc_count = sum(1 for pm in payment_methods if pm.get("payment_id", "").startswith("credit_card_"))
        gc_count = sum(1 for pm in payment_methods if pm.get("payment_id", "").startswith("gift_card_"))
        if cert_count > 1 or cc_count > 1 or gc_count > 3:
            broken.append(("BOOK_PAYMENT_TYPE_LIMIT",
                           "Cannot use more than 1 certificate, 1 credit card, or 3 gift cards."))

        # BOOK_FLIGHTS_CABIN_UNIFORM
        # "Cabin class must be the same across all the flights in a reservation."
        for flightseg in flights:
            flt = get_flight(ctx, flightseg.get("flight_number"))
            if not flt:
                continue
            available_dates = flt.get("dates", {})
            dt = available_dates.get(flightseg.get("date"), {})
            # Checking cabin uniform is trivial: the args pass a single cabin.
            # Should also check all segments' available seats (if status is available)
            if dt.get("status") == "available":
                if cabin not in dt.get("available_seats", {}):
                    broken.append(
                        ("BOOK_FLIGHT_CABIN_AVAIL", f"Cabin '{cabin}' not available for flight {flightseg.get('flight_number')} on {flightseg.get('date')}."))

            # BOOK_AVAIL
            # "flight can only be booked if 'status': 'available'"
            if dt.get("status") != "available":
                broken.append(("BOOK_AVAIL",
                               f"Flight {flightseg.get('flight_number')} on {flightseg.get('date')} is not available for booking."))

            # BOOK_SEAT_AVAIL
            # "Check available seats"
            seats = (dt.get("available_seats", {}) or {}).get(cabin, 0)
            if seats < get_passenger_count(passengers):
                broken.append(("BOOK_SEAT_AVAIL", f"Not enough seats in {cabin} for {flightseg.get('flight_number')} on {flightseg.get('date')}."))

        # BOOK_FREE_BAGGAGE_POLICY
        # "checked bag allowance depends on membership and cabin"
        membership = get_membership(user)
        free_per_pass = calculate_free_bags(membership, cabin)
        free_bags = free_per_pass * get_passenger_count(passengers)
        if total_baggages < 0 or nonfree_baggages < 0:
            broken.append(("BOOK_NEG_BAG", "Baggage numbers must not be negative."))

        if total_baggages < nonfree_baggages or nonfree_baggages < 0:
            broken.append(("BOOK_BAGGAGE_COUNTS", "Nonfree baggages cannot exceed total baggages or be negative."))

        extra_bags = total_baggages - free_bags
        expected_nonfree = max(extra_bags, 0)
        if nonfree_baggages != expected_nonfree:
            broken.append(("BOOK_NONFREE_BAGS_POLICY",
                f"Number of nonfree baggages does not match policy (expected {expected_nonfree}, got {nonfree_baggages})."))

        # BOOK_BAGGAGE_UNNEEDED
        # "Do not add checked bags user does not need." (Can't tell with just records.)

        # BOOK_TRIP_REQUIRED_ARGS
        # Must have flight_type, origin, destination
        if not args.get("origin") or not args.get("destination") or not flight_type:
            broken.append(("BOOK_TRIP_REQUIRED_ARGS", "Booking missing origin, destination, or trip type."))

        # BOOK_INSURANCE_COST
        # If insurance is "yes", $30 per passenger must be charged, else not
        insurance_charged = 30 * get_passenger_count(passengers) if insurance == "yes" else 0
        # Nonfree bag is $50 each
        bag_charge = 50 * (nonfree_baggages or 0)
        # Sum of segment prices for each passenger
        try:
            seg_prices = []
            for flightseg in flights:
                flt = get_flight(ctx, flightseg.get("flight_number"))
                flt_dates = (flt or {}).get("dates", {})
                flt_info = flt_dates.get(flightseg.get("date"), {})
                prices = flt_info.get("prices", {})
                p = prices.get(cabin)
                if p is not None:
                    seg_prices.append(p)
                else:
                    # Fallback: can't get price, but don't block unless it's available (which we checked earlier)
                    pass
            seg_sum = sum(seg_prices) * get_passenger_count(passengers)
        except Exception:
            seg_sum = 0
        total_expected = seg_sum + insurance_charged + bag_charge
        provided = sum_payments(payment_methods)
        if total_expected != provided:
            broken.append(("BOOK_PAYMENT_TOTAL",
                f"Payment sum {provided} does not match expected total {total_expected}."))

    # Cancel reservation
    elif action == "cancel_reservation":
        reservation_id = args.get("reservation_id")
        reservation = get_reservation(ctx, reservation_id)

        if reservation:
            user_id = reservation.get("user_id")
        else:
            user_id = None

        # CANCEL_USERID
        # "agent must obtain user id from user"
        if user_id and user_id not in typed_user_ids:
            broken.append(("CANCEL_USERID", "User id not explicitly provided by the customer."))

        # CANCEL_RESVID
        # "agent must obtain reservation id"
        if reservation_id is None:
            broken.append(("CANCEL_RESVID", "Reservation id is required to cancel."))

        if reservation:
            # CANCEL_IF_FLOWN
            # "If any portion of the flight has already been flown, agent cannot help"
            if any_flight_flown(reservation, ctx):
                broken.append(("CANCEL_IF_FLOWN", "Reservation contains a flown or in-flight segment; cannot cancel."))

            # CANCEL_ELIGIBLE_REASON
            # "Cannot cancel unless: booked within 24h; flight is cancelled by airline; business class; or has insurance and reason covered."
            # We can only see some facts in records; reason comes from conversation, not ctx.
            eligible = False

            # Booking made within last 24hr: compare created_at to now
            create = parse_datetime(reservation.get("created_at"))
            if create:
                diff_hours = (CURRENT_TIME - create).total_seconds() / 3600
                if diff_hours < 24:
                    eligible = True

            # Flight is cancelled by airline in any segment
            if any_flight_cancelled(reservation, ctx):
                eligible = True

            # Business cabin for the reservation
            if reservation.get("cabin") == "business":
                eligible = True

            # Travel insurance: (can only partially check, since we do not see the reason code here)
            if reservation.get("insurance") == "yes":
                # The actual cancellation reason cannot be checked; policy says: block *only* if records show rule is broken.
                # We cannot confirm it's covered, but since we can't determine it's not, do not block.
                eligible = True  # Do not block if insured, per instructions

            if not eligible:
                broken.append(("CANCEL_ELIGIBLE_REASON",
                    "Reservation not cancellable per policy (not within 24hr, not cancelled, not business, not insured)."))

        else:
            broken.append(("CANCEL_NO_RES", "Reservation id given not found in records."))

    # Update reservation flights (modification)
    elif action == "update_reservation_flights":
        res_id = args.get("reservation_id")
        new_cabin = args.get("cabin")
        new_segments = args.get("flights", [])
        payment_id = args.get("payment_id")
        reservation = get_reservation(ctx, res_id)
        user_id = reservation.get("user_id") if reservation else None
        user = get_user(ctx, user_id)

        # MODIFY_USERID
        # "The agent must obtain the user id from the user."
        if user_id and user_id not in typed_user_ids:
            broken.append(("MODIFY_USERID", "User id not provided by customer."))

        # MODIFY_RESVID
        if res_id is None:
            broken.append(("MODIFY_RESVID", "Reservation id required."))

        # MODIFY_PAYMENT_SRC
        # "Payment method must already be in user profile for safety reasons."
        if user and payment_id and not user_has_payment_method(user, payment_id):
            broken.append(("MODIFY_PAYMENT_SRC", "Payment method must be on user profile."))

        # MODIFY_BASIC_ECONOMY_FLIGHT
        # "Basic economy flights cannot be modified."
        if reservation and all_segments_basic_economy(reservation):
            broken.append(("MODIFY_BASIC_ECONOMY_FLIGHT", "Cannot modify basic economy reservation."))

        if reservation:
            # MODIFY_KEEP_FLIGHT_RULES
            orig = reservation
            # "Cannot change origin, destination, or trip type."
            orig_origin = orig.get("origin")
            orig_dest = orig.get("destination")
            orig_trip = orig.get("flight_type")
            new_orig = orig_origin
            new_dest = orig_dest
            flight_type = orig_trip
            # Since the tool doesn't provide origin/dest/flight_type args, but new flights can have different segments,
            # need to check that their origin/destination/trip type matches.
            # We'll check that first flight origin and last flight destination matches.
            if new_segments:
                first_seg = new_segments[0]
                last_seg = new_segments[-1]
                if str(first_seg.get("origin")) != str(orig_origin):
                    broken.append(("MODIFY_ORIGIN_NOCHANGE", "Origin cannot be changed on modification."))
                if str(last_seg.get("destination")) != str(orig_dest):
                    broken.append(("MODIFY_DEST_NOCHANGE", "Destination cannot be changed on modification."))
                # Trip type check: one_way if segments == 1, round_trip if >1 for this DB.
                # (Assume if first flight origin == last flight destination, it's a round trip.)
                # We'll just not block if we can't be sure.

            # MODIFY_CABIN_FLIGHT_FLOWN
            # "Cabin cannot be changed if any segment has already been flown"
            if reservation:
                if new_cabin != reservation.get("cabin"):
                    if any_flight_flown(reservation, ctx):
                        broken.append(("MODIFY_CABIN_FLIGHT_FLOWN", "Cabin cannot be changed after any segment is flown."))

            # MODIFY_CABIN_UNIFORM
            # "Cabin class must be the same across all flights"
            if new_segments:
                for newseg in new_segments:
                    flt = get_flight(ctx, newseg.get("flight_number"))
                    if not flt:
                        continue
                    date_info = (flt.get("dates", {}) or {}).get(newseg.get("date"), {})
                    if date_info:
                        if "available_seats" in date_info and new_cabin not in date_info.get("available_seats", {}):
                            broken.append(("MODIFY_CABIN_UNIFORM", "New cabin not available for one or more new segments."))

        else:
            broken.append(("MODIFY_NO_RES", "Reservation not found for update."))

    # Update reservation baggages
    elif action == "update_reservation_baggages":
        res_id = args.get("reservation_id")
        reservation = get_reservation(ctx, res_id)
        new_total_bag = args.get("total_baggages", 0)
        new_nonfree_bag = args.get("nonfree_baggages", 0)
        payment_id = args.get("payment_id")
        user = get_user(ctx, (reservation or {}).get("user_id"))

        # BAGGAGES_USERID
        if reservation and reservation.get("user_id") and reservation.get("user_id") not in typed_user_ids:
            broken.append(("BAGGAGES_USERID", "User id not provided by customer."))

        # BAGGAGES_PAYMENT_SRC
        if user and payment_id and not user_has_payment_method(user, payment_id):
            broken.append(("BAGGAGES_PAYMENT_SRC", "Payment method must already be on user profile."))

        # BAGGAGES_CANNOT_REMOVE
        # "User can add but not remove checked bags."
        if reservation:
            orig_total_bag = reservation.get("total_baggages", 0)
            if new_total_bag < orig_total_bag:
                broken.append(("BAGGAGES_CANNOT_REMOVE", "Cannot remove checked bags, can only add."))
            orig_nonfree = reservation.get("nonfree_baggages", 0)
            if new_nonfree_bag < orig_nonfree:
                broken.append(("BAGGAGES_CANNOT_REMOVE_NONFREE", "Cannot decrease nonfree baggages."))


    # Update reservation passengers
    elif action == "update_reservation_passengers":
        res_id = args.get("reservation_id")
        passenger_list = args.get("passengers", [])
        reservation = get_reservation(ctx, res_id)

        # PASSENGERS_USERID
        if reservation and reservation.get("user_id") and reservation.get("user_id") not in typed_user_ids:
            broken.append(("PASSENGERS_USERID", "User id not provided by customer."))

        # PASSENGERS_NO_NUMBER_CHANGE
        # "The user can modify passengers but cannot modify the number of passengers."
        if reservation:
            orig_num = get_passenger_count(reservation.get("passengers", []))
            new_num = get_passenger_count(passenger_list)
            if orig_num != new_num:
                broken.append(("PASSENGERS_NO_NUMBER_CHANGE",
                    f"Number of passengers cannot be changed (was {orig_num}, now {new_num})."))

    # send_certificate
    elif action == "send_certificate":
        user_id = args.get("user_id")
        amount = args.get("amount", 0)
        user = get_user(ctx, user_id)

        # CERT_USERID
        if user_id not in typed_user_ids:
            broken.append(("CERT_USERID", "User id not explicitly provided by user."))

        # For compensation, check recent conversation & triggers:
        # The agent may only offer compensation if:
        #   - user is silver/gold, or
        #   - has travel insurance, or
        #   - flies business
        is_eligible = False

        # Check membership
        member_level = get_membership(user)
        if member_level in {"gold", "silver"}:
            is_eligible = True

        # Has travel insurance in at least one reservation.
        insured_res = False
        for res_id in (user.get("reservations") or []):
            res = get_reservation(ctx, res_id)
            if res and res.get("insurance") == "yes":
                insured_res = True
                break
        if insured_res:
            is_eligible = True

        # Flies business in any reservation
        business_res = False
        for res_id in (user.get("reservations") or []):
            res = get_reservation(ctx, res_id)
            if res and res.get("cabin") == "business":
                business_res = True
                break
        if business_res:
            is_eligible = True

        if not is_eligible:
            broken.append(("CERT_ELIGIBLE_POLICY",
                "Compensation can only be offered to gold/silver members, users with insurance, or business cabin flyers."))

    # ---- Cross-cutting and Interface policy checks ----

    # INFERRED_CONFIRMED_POLICY
    # For any write, policy: "must list action details and obtain explicit user confirmation (yes) to proceed".
    # The agent is responsible for this, but we cannot see explicit confirmation in records;
    # so by instructions, do not block unless records clearly show the confirmation is missing.

    # INFERRED_TOOL_RESPONSE_SEPARATION
    # "You should only make one tool call at a time, and if you make a tool call, you should not respond to the user simultaneously."
    # This needs dialogue flow -- do not enforce in preflight checks as only records are visible.

    # INFERRED_DO_NOT_GUESS_POLICY
    # "Do not block unless records clearly show policy rule is broken, do not guess gaps in data."
    # No extra blocking here.

    return broken
```
