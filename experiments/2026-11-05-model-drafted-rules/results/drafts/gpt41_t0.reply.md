```python
from datetime import datetime, timedelta

CURRENT_TIME = datetime(2024, 5, 15, 15, 0, 0)  # EST

def parse_datetime(dt_str):
    # Handles both date and datetime strings
    if dt_str is None:
        return None
    try:
        if "T" in dt_str:
            return datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%S")
        else:
            return datetime.strptime(dt_str, "%Y-%m-%d")
    except Exception:
        return None

def get_user(ctx, user_id):
    return ctx.db.get("users", {}).get(user_id)

def get_reservation(ctx, reservation_id):
    return ctx.db.get("reservations", {}).get(reservation_id)

def get_flight(ctx, flight_number):
    return ctx.db.get("flights", {}).get(flight_number)

def get_reservation_flights(ctx, reservation):
    # Returns list of (flight_number, date, cabin)
    flights = []
    for f in reservation.get("flights", []):
        flights.append((f.get("flight_number"), f.get("date"), reservation.get("cabin")))
    return flights

def get_flight_status(ctx, flight_number, date):
    flight = get_flight(ctx, flight_number)
    if not flight:
        return None
    return flight.get("dates", {}).get(date, {}).get("status")

def get_flight_info(ctx, flight_number, date):
    flight = get_flight(ctx, flight_number)
    if not flight:
        return None
    return flight.get("dates", {}).get(date)

def get_membership(user):
    return (user or {}).get("membership")

def get_payment_methods(user):
    return set((user or {}).get("payment_methods", {}).keys())

def get_payment_method_sources(user):
    # Returns dict: id -> source
    return {pm["id"]: pm["source"] for pm in (user or {}).get("payment_methods", {}).values()}

def get_reservation_user_id(ctx, reservation_id):
    reservation = get_reservation(ctx, reservation_id)
    if reservation:
        return reservation.get("user_id")
    return None

def get_reservation_passenger_count(reservation):
    return len(reservation.get("passengers", []))

def get_reservation_status(reservation):
    return reservation.get("status")

def get_reservation_created_at(reservation):
    return parse_datetime(reservation.get("created_at"))

def get_reservation_cabin(reservation):
    return reservation.get("cabin")

def get_reservation_flight_segments(reservation):
    return reservation.get("flights", [])

def get_reservation_insurance(reservation):
    return reservation.get("insurance")

def get_reservation_baggages(reservation):
    return reservation.get("total_baggages", 0), reservation.get("nonfree_baggages", 0)

def get_reservation_payment_history(reservation):
    return reservation.get("payment_history", [])

def get_reservation_origin_destination(reservation):
    return reservation.get("origin"), reservation.get("destination")

def get_reservation_trip_type(reservation):
    return reservation.get("flight_type")

def get_reservation_flight_dates(reservation):
    return [f.get("date") for f in reservation.get("flights", []) if f.get("date")]

def any_flight_flown(ctx, reservation):
    # Returns True if any flight in reservation has status "landed" or "flying"
    for f in reservation.get("flights", []):
        status = get_flight_status(ctx, f.get("flight_number"), f.get("date"))
        if status in ("landed", "flying"):
            return True
    return False

def all_flights_basic_economy(reservation):
    return reservation.get("cabin") == "basic_economy"

def all_flights_same_cabin(flights, cabin):
    return all(f.get("cabin") == cabin for f in flights)

def get_passenger_key(passenger):
    return (passenger.get("first_name", "").strip().lower(),
            passenger.get("last_name", "").strip().lower(),
            passenger.get("dob", "").strip())

def passengers_match(passengers1, passengers2):
    # Returns True if both lists have same passengers (order doesn't matter)
    set1 = set(get_passenger_key(p) for p in passengers1)
    set2 = set(get_passenger_key(p) for p in passengers2)
    return set1 == set2

def get_confirmation_from_prior_writes(ctx):
    # Returns True if a confirmation was recorded in prior_writes for this action
    # We assume that confirmation is tracked outside this module; so we cannot check it here.
    # The policy says: "Before taking any actions that update the booking database ... you must list the action details and obtain explicit user confirmation (yes) to proceed."
    # But we cannot check conversation state, so we cannot enforce this here.
    return True

def check(ctx):
    errors = []

    # --- BOOK RESERVATION ---
    if ctx.action == "book_reservation":
        args = ctx.args
        user_id = args.get("user_id")
        user = get_user(ctx, user_id)
        # BOOK_USERID: Must have user id from user
        if not user_id or user_id not in ctx.typed_user_ids:
            errors.append(("BOOK_USERID", "User id must be provided by the user."))

        # BOOK_PASSENGER_COUNT: At most 5 passengers
        passengers = args.get("passengers", [])
        if len(passengers) > 5:
            errors.append(("BOOK_PASSENGER_COUNT", "Cannot book more than 5 passengers in one reservation."))

        # BOOK_CABIN_UNIFORM: Cabin class must be the same across all flights
        flights = args.get("flights", [])
        cabin = args.get("cabin")
        for f in flights:
            flight = get_flight(ctx, f.get("flight_number"))
            if not flight:
                continue
            date_info = flight.get("dates", {}).get(f.get("date"), {})
            # No explicit cabin per segment in booking, so nothing to check here

        # BOOK_PAYMENT_METHODS: Payment methods must be in user profile
        payment_methods = args.get("payment_methods", [])
        user_pm_ids = get_payment_methods(user)
        for pm in payment_methods:
            if pm.get("payment_id") not in user_pm_ids:
                errors.append(("BOOK_PAYMENT_METHODS", "All payment methods must be in user profile."))

        # BOOK_PAYMENT_LIMITS: At most 1 travel certificate, 1 credit card, 3 gift cards
        pm_sources = [get_payment_method_sources(user).get(pm.get("payment_id")) for pm in payment_methods]
        if pm_sources.count("certificate") > 1:
            errors.append(("BOOK_PAYMENT_LIMITS", "At most one travel certificate per reservation."))
        if pm_sources.count("credit_card") > 1:
            errors.append(("BOOK_PAYMENT_LIMITS", "At most one credit card per reservation."))
        if pm_sources.count("gift_card") > 3:
            errors.append(("BOOK_PAYMENT_LIMITS", "At most three gift cards per reservation."))

        # BOOK_BAGGAGE_ALLOWANCE: Do not add checked bags user does not need (cannot check, as we don't know what user needs)
        # BOOK_BAGGAGE_POLICY: Checked bag allowance per membership/cabin (cannot check, as we don't know what user needs)

        # BOOK_INSURANCE: Must ask if user wants insurance (cannot check, as we don't know what user said)

        # BOOK_SEAT_AVAILABILITY: Each flight must be available and have enough seats in the requested cabin
        for f in flights:
            flight = get_flight(ctx, f.get("flight_number"))
            if not flight:
                errors.append(("BOOK_FLIGHT_EXISTS", f"Flight {f.get('flight_number')} does not exist."))
                continue
            date_info = flight.get("dates", {}).get(f.get("date"))
            if not date_info:
                errors.append(("BOOK_FLIGHT_DATE", f"Flight {f.get('flight_number')} does not operate on {f.get('date')}."))
                continue
            if date_info.get("status") != "available":
                errors.append(("BOOK_FLIGHT_STATUS", f"Flight {f.get('flight_number')} on {f.get('date')} is not available for booking."))
                continue
            available = date_info.get("available_seats", {}).get(cabin, 0)
            if available < len(passengers):
                errors.append(("BOOK_SEAT_AVAILABILITY", f"Not enough seats in {cabin} on flight {f.get('flight_number')} {f.get('date')}."))

        # BOOK_CABIN_VALID: Cabin must be one of allowed values
        if cabin not in ("basic_economy", "economy", "business"):
            errors.append(("BOOK_CABIN_VALID", "Cabin class must be basic_economy, economy, or business."))

        # BOOK_PAYMENT_TOTAL: Payment amounts must add up to total price
        # Compute expected price
        total_price = 0
        for f in flights:
            flight = get_flight(ctx, f.get("flight_number"))
            if not flight:
                continue
            date_info = flight.get("dates", {}).get(f.get("date"), {})
            price = date_info.get("prices", {}).get(cabin)
            if price is None:
                continue
            total_price += price * len(passengers)
        if args.get("insurance") == "yes":
            total_price += 30 * len(passengers)
        total_baggages = args.get("total_baggages", 0)
        nonfree_baggages = args.get("nonfree_baggages", 0)
        total_price += 50 * nonfree_baggages
        payment_sum = sum(pm.get("amount", 0) for pm in payment_methods)
        if abs(payment_sum - total_price) > 0.01:
            errors.append(("BOOK_PAYMENT_TOTAL", "Payment amounts do not add up to total price."))

    # --- CANCEL RESERVATION ---
    elif ctx.action == "cancel_reservation":
        args = ctx.args
        reservation_id = args.get("reservation_id")
        reservation = get_reservation(ctx, reservation_id)
        if not reservation:
            errors.append(("CANCEL_RESERVATION_EXISTS", "Reservation does not exist."))
        else:
            # CANCEL_USERID: Must have user id from user
            user_id = reservation.get("user_id")
            if not user_id or user_id not in ctx.typed_user_ids:
                errors.append(("CANCEL_USERID", "User id must be provided by the user."))

            # CANCEL_ALREADY_FLOWN: Cannot cancel if any portion already flown
            if any_flight_flown(ctx, reservation):
                errors.append(("CANCEL_ALREADY_FLOWN", "Cannot cancel reservation with any flown segment."))

            # CANCEL_ELIGIBILITY: Must meet one of the cancellation conditions
            # The API does not check these for the agent, so the agent must make sure the rules apply before calling the API!
            # - Booking made within last 24 hrs
            # - Flight is cancelled by airline
            # - It is a business flight
            # - User has travel insurance and reason is covered by insurance
            # We cannot check the reason for cancellation (conversation only), so only check what we can.
            created_at = get_reservation_created_at(reservation)
            within_24h = False
            if created_at:
                within_24h = (CURRENT_TIME - created_at) <= timedelta(hours=24)
            any_cancelled = any(get_flight_status(ctx, f.get("flight_number"), f.get("date")) == "cancelled"
                                for f in reservation.get("flights", []))
            is_business = reservation.get("cabin") == "business"
            has_insurance = reservation.get("insurance") == "yes"
            if not (within_24h or any_cancelled or is_business or has_insurance):
                errors.append(("CANCEL_ELIGIBILITY", "Reservation is not eligible for cancellation by policy."))

    # --- UPDATE RESERVATION FLIGHTS ---
    elif ctx.action == "update_reservation_flights":
        args = ctx.args
        reservation_id = args.get("reservation_id")
        reservation = get_reservation(ctx, reservation_id)
        if not reservation:
            errors.append(("MODIFY_RESERVATION_EXISTS", "Reservation does not exist."))
        else:
            # MODIFY_USERID: Must have user id from user
            user_id = reservation.get("user_id")
            if not user_id or user_id not in ctx.typed_user_ids:
                errors.append(("MODIFY_USERID", "User id must be provided by the user."))

            # MODIFY_BASIC_ECONOMY: Basic economy flights cannot be modified
            if reservation.get("cabin") == "basic_economy":
                errors.append(("MODIFY_BASIC_ECONOMY", "Basic economy reservations cannot be modified."))

            # MODIFY_ORIGIN_DEST_TYPE: Cannot change origin, destination, or trip type
            orig, dest = get_reservation_origin_destination(reservation)
            new_flights = args.get("flights", [])
            if new_flights:
                # Check that all new flights have same origin/destination as reservation
                for f in new_flights:
                    flight = get_flight(ctx, f.get("flight_number"))
                    if not flight:
                        continue
                    if flight.get("origin") != orig or flight.get("destination") != dest:
                        errors.append(("MODIFY_ORIGIN_DEST_TYPE", "Cannot change origin or destination when modifying flights."))
                        break
            if args.get("cabin") and args.get("cabin") not in ("basic_economy", "economy", "business"):
                errors.append(("MODIFY_CABIN_VALID", "Cabin class must be basic_economy, economy, or business."))

            # MODIFY_CABIN_CHANGE_AFTER_FLOWN: Cannot change cabin if any flight already flown
            if args.get("cabin") and args.get("cabin") != reservation.get("cabin"):
                if any_flight_flown(ctx, reservation):
                    errors.append(("MODIFY_CABIN_CHANGE_AFTER_FLOWN", "Cannot change cabin if any flight already flown."))

            # MODIFY_CABIN_UNIFORM: Cabin class must be same across all flights
            # (API only allows one cabin per reservation, so this is enforced by schema)

            # MODIFY_PAYMENT_METHOD: Payment method must be in user profile
            payment_id = args.get("payment_id")
            user_pm_ids = get_payment_methods(get_user(ctx, user_id))
            if payment_id and payment_id not in user_pm_ids:
                errors.append(("MODIFY_PAYMENT_METHOD", "Payment method must be in user profile."))

    # --- UPDATE RESERVATION BAGGAGES ---
    elif ctx.action == "update_reservation_baggages":
        args = ctx.args
        reservation_id = args.get("reservation_id")
        reservation = get_reservation(ctx, reservation_id)
        if not reservation:
            errors.append(("BAGGAGE_RESERVATION_EXISTS", "Reservation does not exist."))
        else:
            # BAGGAGE_USERID: Must have user id from user
            user_id = reservation.get("user_id")
            if not user_id or user_id not in ctx.typed_user_ids:
                errors.append(("BAGGAGE_USERID", "User id must be provided by the user."))

            # BAGGAGE_ADD_ONLY: Can add but not remove checked bags
            prev_total, prev_nonfree = get_reservation_baggages(reservation)
            new_total = args.get("total_baggages", 0)
            new_nonfree = args.get("nonfree_baggages", 0)
            if new_total < prev_total or new_nonfree < prev_nonfree:
                errors.append(("BAGGAGE_ADD_ONLY", "Cannot remove checked bags; only adding is allowed."))

            # BAGGAGE_PAYMENT_METHOD: Payment method must be in user profile
            payment_id = args.get("payment_id")
            user_pm_ids = get_payment_methods(get_user(ctx, user_id))
            if payment_id and payment_id not in user_pm_ids:
                errors.append(("BAGGAGE_PAYMENT_METHOD", "Payment method must be in user profile."))

    # --- UPDATE RESERVATION PASSENGERS ---
    elif ctx.action == "update_reservation_passengers":
        args = ctx.args
        reservation_id = args.get("reservation_id")
        reservation = get_reservation(ctx, reservation_id)
        if not reservation:
            errors.append(("PASSENGER_RESERVATION_EXISTS", "Reservation does not exist."))
        else:
            # PASSENGER_USERID: Must have user id from user
            user_id = reservation.get("user_id")
            if not user_id or user_id not in ctx.typed_user_ids:
                errors.append(("PASSENGER_USERID", "User id must be provided by the user."))

            # PASSENGER_COUNT_UNCHANGED: Cannot modify number of passengers
            old_passengers = reservation.get("passengers", [])
            new_passengers = args.get("passengers", [])
            if len(old_passengers) != len(new_passengers):
                errors.append(("PASSENGER_COUNT_UNCHANGED", "Cannot change the number of passengers in a reservation."))

    # --- SEND CERTIFICATE (COMPENSATION) ---
    elif ctx.action == "send_certificate":
        args = ctx.args
        user_id = args.get("user_id")
        user = get_user(ctx, user_id)
        # COMPENSATE_ELIGIBILITY: Only compensate if user is silver/gold or has insurance or flies business
        eligible = False
        if user:
            if user.get("membership") in ("silver", "gold"):
                eligible = True
            # Check if user has any reservation with insurance or business cabin
            for rid in user.get("reservations", []):
                reservation = get_reservation(ctx, rid)
                if reservation:
                    if reservation.get("insurance") == "yes":
                        eligible = True
                    if reservation.get("cabin") == "business":
                        eligible = True
        if not eligible:
            errors.append(("COMPENSATE_ELIGIBILITY", "User is not eligible for compensation (must be silver/gold member, have insurance, or fly business)."))

    # --- INFERRED RULES ---
    # INFERRED_NO_CONVERSATION_CONFIRM: Cannot check for explicit user confirmation (conversation only)
    # INFERRED_NO_REASON: Cannot check cancellation reason (conversation only)
    # INFERRED_NO_COMPENSATION_REQUEST: Cannot check if user explicitly asked for compensation (conversation only)
    # INFERRED_NO_FACT_CONFIRM: Cannot check if facts were confirmed before compensation (conversation only)

    return errors
```