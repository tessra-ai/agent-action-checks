from datetime import datetime, timedelta

CURRENT_TIME = datetime.fromisoformat("2024-05-15T15:00:00")

def parse_iso_datetime(dtstr):
    try:
        return datetime.fromisoformat(dtstr)
    except Exception:
        return None

def parse_iso_date(dstr):
    try:
        return datetime.fromisoformat(dstr + "T00:00:00")
    except Exception:
        return None

def cabin_class_consistent(flights, cabin):
    # Check all flights have the same cabin class (for booking/modifying)
    # flights is list of dicts with flight_number and date
    # cabin is string
    return True  # We cannot check here because flights do not carry cabin in args except modify

def payment_methods_valid(user_payment_methods, payment_methods):
    # Check payment methods used are in user's profile and counts limits for booking
    # payment_methods is list of dicts with payment_id and amount
    # user_payment_methods is dict keyed by payment_id
    if not payment_methods or not user_payment_methods:
        return False
    travel_cert_count = 0
    credit_card_count = 0
    gift_card_count = 0
    for pm in payment_methods:
        pid = pm.get("payment_id")
        if pid not in user_payment_methods:
            return False
        source = user_payment_methods[pid].get("source")
        if source == "travel_certificate":
            travel_cert_count += 1
        elif source == "credit_card":
            credit_card_count += 1
        elif source == "gift_card":
            gift_card_count += 1
        else:
            # unknown payment source
            return False
    if travel_cert_count > 1 or credit_card_count > 1 or gift_card_count > 3:
        return False
    return True

def flights_all_available(db_flights, flights, cabin):
    # Check all flights exist and are available for booking in the given cabin class
    # flights is list of dicts with flight_number and date
    for f in flights:
        fn = f.get("flight_number")
        date = f.get("date")
        if not fn or not date:
            return False
        flight = db_flights.get(fn)
        if not flight:
            return False
        date_info = flight.get("dates", {}).get(date)
        if not date_info:
            return False
        status = date_info.get("status")
        if status != "available":
            return False
        # Check cabin class availability
        seats = date_info.get("available_seats", {})
        prices = date_info.get("prices", {})
        if cabin not in seats or cabin not in prices:
            return False
        if seats[cabin] <= 0:
            return False
    return True

def passengers_valid(passengers):
    # Check passengers count and fields
    if not passengers or not isinstance(passengers, list):
        return False
    if len(passengers) > 5:
        return False
    for p in passengers:
        if not isinstance(p, dict):
            return False
        if not p.get("first_name") or not p.get("last_name") or not p.get("dob"):
            return False
    return True

def baggage_counts_valid(total_baggages, nonfree_baggages):
    # nonfree_baggages <= total_baggages and both >= 0
    if total_baggages is None or nonfree_baggages is None:
        return False
    if not isinstance(total_baggages, int) or not isinstance(nonfree_baggages, int):
        return False
    if total_baggages < 0 or nonfree_baggages < 0:
        return False
    if nonfree_baggages > total_baggages:
        return False
    return True

def user_has_payment_method(user, payment_id):
    if not user or not payment_id:
        return False
    return payment_id in user.get("payment_methods", {})

def reservation_flights_same_origin_destination_trip(reservation, new_origin, new_destination, new_trip_type):
    # Check if origin, destination, trip_type unchanged
    if not reservation:
        return False
    if new_origin != reservation.get("origin"):
        return False
    if new_destination != reservation.get("destination"):
        return False
    if new_trip_type != reservation.get("flight_type"):
        return False
    return True

def flights_basic_economy(flights, db_flights):
    # Return True if all flights are basic economy class (used for modify flight restrictions)
    # flights is list of dicts with flight_number and date
    # We cannot know cabin from flights alone, so this function is not reliable here.
    # We rely on reservation cabin for modify.
    return False

def flights_flown(flights, db_flights):
    # Return True if any flight segment has status "flying" or "landed"
    for f in flights:
        fn = f.get("flight_number")
        date = f.get("date")
        if not fn or not date:
            continue
        flight = db_flights.get(fn)
        if not flight:
            continue
        date_info = flight.get("dates", {}).get(date)
        if not date_info:
            continue
        status = date_info.get("status")
        if status in ("flying", "landed"):
            return True
    return False

def reservation_flights_flown(reservation, db_flights):
    if not reservation:
        return False
    return flights_flown(reservation.get("flights", []), db_flights)

def passengers_same_count(old_passengers, new_passengers):
    if not isinstance(old_passengers, list) or not isinstance(new_passengers, list):
        return False
    return len(old_passengers) == len(new_passengers)

def payment_method_single_gift_or_credit(user, payment_id):
    # Check payment_id is single gift card or credit card in user profile
    if not user or not payment_id:
        return False
    pm = user.get("payment_methods", {}).get(payment_id)
    if not pm:
        return False
    source = pm.get("source")
    return source in ("gift_card", "credit_card")

def reservation_created_within_24h(reservation):
    if not reservation:
        return False
    created_at = reservation.get("created_at")
    if not created_at:
        return False
    dt = parse_iso_datetime(created_at)
    if not dt:
        return False
    delta = CURRENT_TIME - dt
    return delta <= timedelta(hours=24)

def reservation_has_travel_insurance(reservation):
    if not reservation:
        return False
    return reservation.get("insurance") == "yes"

def reservation_is_business(reservation):
    if not reservation:
        return False
    return reservation.get("cabin") == "business"

def reservation_status_cancelled(reservation):
    if not reservation:
        return False
    return reservation.get("status") == "cancelled"

def user_membership_level(user):
    if not user:
        return None
    return user.get("membership")

def reservation_passengers_count(reservation):
    if not reservation:
        return 0
    ps = reservation.get("passengers")
    if not ps:
        return 0
    return len(ps)

def check(ctx) -> list[tuple[str, str]]:
    errors = []
    db = ctx.db
    action = ctx.action
    args = ctx.args

    # Helper to get user from typed_user_ids or args
    def get_user():
        # Prefer user_id in args if present
        uid = None
        if action == "book_reservation":
            uid = args.get("user_id")
        else:
            # For modify, cancel, update, try args user_id or typed_user_ids
            uid = args.get("user_id")
            if not uid and ctx.typed_user_ids:
                # If only one typed user id, use it
                if len(ctx.typed_user_ids) == 1:
                    uid = next(iter(ctx.typed_user_ids))
        if uid and uid in db.get("users", {}):
            return db["users"][uid]
        return None

    user = get_user()

    # RULE BOOK_1: # Before booking, user_id must be provided and valid
    if action == "book_reservation":
        uid = args.get("user_id")
        if not uid or uid not in db.get("users", {}):
            errors.append(("BOOK_1", "Booking requires a valid user_id."))

        # RULE BOOK_2: Cabin class must be consistent across all flights (implied by booking API)
        cabin = args.get("cabin")
        flights = args.get("flights")
        if not cabin or not flights or not isinstance(flights, list) or len(flights) == 0:
            errors.append(("BOOK_2", "Booking requires cabin and at least one flight."))
        else:
            # Check all flights are available on given dates and cabin
            if not flights_all_available(db.get("flights", {}), flights, cabin):
                errors.append(("BOOK_2", "All flights must be available for booking in the chosen cabin."))

        # RULE BOOK_3: Passengers count max 5 and all have first_name, last_name, dob
        passengers = args.get("passengers")
        if not passengers_valid(passengers):
            errors.append(("BOOK_3", "Booking requires 1 to 5 passengers with first_name, last_name, dob."))

        # RULE BOOK_4: Payment methods must be in user profile and limits respected
        payment_methods = args.get("payment_methods")
        if user:
            if not payment_methods_valid(user.get("payment_methods", {}), payment_methods):
                errors.append(("BOOK_4", "Payment methods must be in user profile and respect limits."))

        # RULE BOOK_5: total_baggages and nonfree_baggages valid counts
        total_baggages = args.get("total_baggages")
        nonfree_baggages = args.get("nonfree_baggages")
        if not baggage_counts_valid(total_baggages, nonfree_baggages):
            errors.append(("BOOK_5", "Invalid baggage counts."))

        # RULE BOOK_6: insurance must be "yes" or "no"
        insurance = args.get("insurance")
        if insurance not in ("yes", "no"):
            errors.append(("BOOK_6", "Insurance must be 'yes' or 'no'."))

    elif action == "cancel_reservation":
        # RULE CANCEL_1: user_id and reservation_id must be provided and valid
        uid = args.get("user_id")
        rid = args.get("reservation_id")
        if not uid or uid not in db.get("users", {}):
            errors.append(("CANCEL_1", "Cancellation requires valid user_id."))
        if not rid or rid not in db.get("reservations", {}):
            errors.append(("CANCEL_1", "Cancellation requires valid reservation_id."))

        if errors:
            return errors

        reservation = db["reservations"].get(rid)
        if not reservation:
            errors.append(("CANCEL_1", "Reservation not found."))

        # RULE CANCEL_2: If any flight flown, cannot cancel (transfer needed)
        if reservation_flights_flown(reservation, db.get("flights", {})):
            errors.append(("CANCEL_2", "Cannot cancel reservation with any flown flight segment."))

        # RULE CANCEL_3: Cancellation allowed only if:
        # - booked within last 24h
        # - flight cancelled by airline
        # - business flight
        # - user has insurance and reason covered by insurance
        # We only check what we can from records; reason is not in args, so skip that condition

        # Check booking time
        booked_within_24h = reservation_created_within_24h(reservation)

        # Check if any flight cancelled by airline
        flights_cancelled = False
        for f in reservation.get("flights", []):
            fn = f.get("flight_number")
            date = f.get("date")
            if not fn or not date:
                continue
            flight = db.get("flights", {}).get(fn)
            if not flight:
                continue
            date_info = flight.get("dates", {}).get(date)
            if not date_info:
                continue
            if date_info.get("status") == "cancelled":
                flights_cancelled = True
                break

        # Check business flight
        is_business = reservation_is_business(reservation)

        # Check insurance
        has_insurance = reservation_has_travel_insurance(reservation)

        # Reason for cancellation is not in args, so cannot check insurance coverage condition

        if not (booked_within_24h or flights_cancelled or is_business or has_insurance):
            errors.append(("CANCEL_3", "Cancellation conditions not met."))

    elif action == "update_reservation_flights":
        # RULE MODIFY_1: user_id and reservation_id must be provided and valid
        uid = args.get("user_id")
        rid = args.get("reservation_id")
        if not uid or uid not in db.get("users", {}):
            errors.append(("MODIFY_1", "Modification requires valid user_id."))
        if not rid or rid not in db.get("reservations", {}):
            errors.append(("MODIFY_1", "Modification requires valid reservation_id."))

        if errors:
            return errors

        reservation = db["reservations"].get(rid)
        if not reservation:
            errors.append(("MODIFY_1", "Reservation not found."))

        if errors:
            return errors

        # RULE MODIFY_2: Basic economy flights cannot be modified (change flights)
        # Cabin is in args, flights in args
        new_cabin = args.get("cabin")
        new_flights = args.get("flights")
        if not new_cabin or not new_flights or not isinstance(new_flights, list) or len(new_flights) == 0:
            errors.append(("MODIFY_2", "Modification requires cabin and flights."))

        # Check if original reservation cabin is basic economy and flights changed
        if reservation.get("cabin") == "basic_economy":
            # If flights changed, block
            # Compare old flights and new flights by flight_number and date
            old_flights = reservation.get("flights", [])
            if old_flights != new_flights:
                errors.append(("MODIFY_2", "Basic economy flights cannot be modified."))

        # RULE MODIFY_3: For flight changes, origin, destination, trip type must not change
        if not reservation_flights_same_origin_destination_trip(reservation,
                                                               reservation.get("origin"),
                                                               reservation.get("destination"),
                                                               reservation.get("flight_type")):
            # This is original reservation, so no error here
            pass
        else:
            # Check new flights origin/destination/trip type not changed
            # We only have flights and cabin in args, no origin/destination/trip_type in args
            # So we assume no change in origin/destination/trip_type for modify flights call
            pass

        # RULE MODIFY_4: Cabin class must be same across all flights
        # We cannot check cabin per flight here, assume cabin arg applies to all flights

        # RULE MODIFY_5: Cabin cannot be changed if any flight flown
        if new_cabin != reservation.get("cabin"):
            if reservation_flights_flown(reservation, db.get("flights", {})):
                errors.append(("MODIFY_5", "Cannot change cabin if any flight already flown."))

        # RULE MODIFY_6: Payment method must be single gift card or credit card in user profile
        payment_id = args.get("payment_id")
        if not payment_method_single_gift_or_credit(user, payment_id):
            errors.append(("MODIFY_6", "Payment method must be single gift card or credit card in user profile."))

    elif action == "update_reservation_baggages":
        # RULE BAG_1: user_id and reservation_id must be provided and valid
        uid = args.get("user_id")
        rid = args.get("reservation_id")
        if not uid or uid not in db.get("users", {}):
            errors.append(("BAG_1", "Baggage update requires valid user_id."))
        if not rid or rid not in db.get("reservations", {}):
            errors.append(("BAG_1", "Baggage update requires valid reservation_id."))

        if errors:
            return errors

        reservation = db["reservations"].get(rid)
        if not reservation:
            errors.append(("BAG_1", "Reservation not found."))

        if errors:
            return errors

        # RULE BAG_2: User can add but not remove checked bags
        # So new total_baggages >= old total_baggages
        new_total = args.get("total_baggages")
        new_nonfree = args.get("nonfree_baggages")
        if not baggage_counts_valid(new_total, new_nonfree):
            errors.append(("BAG_2", "Invalid baggage counts."))

        old_total = reservation.get("total_baggages")
        old_nonfree = reservation.get("nonfree_baggages")
        if old_total is not None and new_total is not None:
            if new_total < old_total:
                errors.append(("BAG_2", "Cannot remove checked bags, only add."))

        if old_nonfree is not None and new_nonfree is not None:
            if new_nonfree < old_nonfree:
                errors.append(("BAG_2", "Cannot remove nonfree checked bags, only add."))

        # RULE BAG_3: Payment method must be single gift card or credit card in user profile
        payment_id = args.get("payment_id")
        if not payment_method_single_gift_or_credit(user, payment_id):
            errors.append(("BAG_3", "Payment method must be single gift card or credit card in user profile."))

    elif action == "update_reservation_passengers":
        # RULE PASS_1: user_id and reservation_id must be provided and valid
        uid = args.get("user_id")
        rid = args.get("reservation_id")
        if not uid or uid not in db.get("users", {}):
            errors.append(("PASS_1", "Passenger update requires valid user_id."))
        if not rid or rid not in db.get("reservations", {}):
            errors.append(("PASS_1", "Passenger update requires valid reservation_id."))

        if errors:
            return errors

        reservation = db["reservations"].get(rid)
        if not reservation:
            errors.append(("PASS_1", "Reservation not found."))

        if errors:
            return errors

        # RULE PASS_2: Cannot modify number of passengers
        old_passengers = reservation.get("passengers")
        new_passengers = args.get("passengers")
        if not passengers_valid(new_passengers):
            errors.append(("PASS_2", "Passengers must have first_name, last_name, dob and max 5."))
        else:
            if not passengers_same_count(old_passengers, new_passengers):
                errors.append(("PASS_2", "Cannot modify number of passengers."))

    elif action == "send_certificate":
        # RULE COMP_1: Only compensate if user is silver/gold or has insurance or flies business
        uid = args.get("user_id")
        amount = args.get("amount")
        if not uid or uid not in db.get("users", {}):
            errors.append(("COMP_1", "Compensation requires valid user_id."))
        else:
            user = db["users"][uid]
            membership = user_membership_level(user)
            # We cannot know reservation here, so we cannot check flights or insurance
            # So only allow if membership is silver or gold
            if membership not in ("silver", "gold"):
                # Check if user has any reservation with insurance or business flight
                has_qualifying_reservation = False
                for rid in user.get("reservations", []):
                    res = db.get("reservations", {}).get(rid)
                    if not res:
                        continue
                    if reservation_has_travel_insurance(res):
                        has_qualifying_reservation = True
                        break
                    if reservation_is_business(res):
                        has_qualifying_reservation = True
                        break
                if not has_qualifying_reservation:
                    errors.append(("COMP_1", "User not eligible for compensation."))

    else:
        # Unknown action: allow by default (no blocking)
        pass

    return errors
