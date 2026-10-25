from math import asin, cos, radians, sin, sqrt

# the API receives a location name, but each name is mapped to its coordinates
# (latitude, longitude) for easy lookup and distance calculations
CITIES = {
    "toronto": (43.6532, -79.3832),
    "vancouver": (49.2827, -123.1207),
    "montreal": (45.5017, -73.5673),
    "ottawa": (45.4215, -75.6972),
    "calgary": (51.0447, -114.0719),
    "halifax": (44.6488, -63.5752),
    "new york": (40.7128, -74.0060),
    "london": (51.5074, -0.1278),
    "lagos": (6.5244, 3.3792),
}


def haversine_km(location_a, location_b):
    # calculating the distance between locations using their coordinates (haversine formula)
    lat1, lon1 = location_a
    lat2, lon2 = location_b
    lat1, lon1, lat2, lon2 = radians(lat1), radians(lon1), radians(lat2), radians(lon2)
    h = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * asin(sqrt(h))


def check_large_amount(transaction_type, amount, settings):
    # check if a withdrawal or transfer is considered large or not, by checking the transaction type and amount alongside the max set. deposits are not checked.
    if transaction_type in ("withdrawal", "transfer") and amount > settings.max_amount:
        return f"unusually high {transaction_type} amount"
    return None


def check_impossible_travel(location, timestamp, previous, settings):
    if previous is None:
        return None  #then there is nothing to compare this rule to.
    here = CITIES.get(location.strip().lower())
    there = CITIES.get(previous["location"].strip().lower())
    if here is None or there is None:
        return None  # unknown city. meaning we cannot judge, so this rule is skipped
    distance = haversine_km(here, there)
    if distance == 0:
        return None  # same place

    # minimum time needed to travel there (distance / speed) plus a buffer to account for delays or unexpected stuffs.
    required_min = distance / settings.max_travel_speed_kmh * 60 + settings.travel_buffer_min
    gap_min = max((timestamp - previous["timestamp"]).total_seconds() / 60, 0)
    # if time is lesser than the trip time, then the trip was is not possible.
    if gap_min < required_min:
        return "unusual location, too far from the previous transaction for the time that passed"
    return None


def check_failed_logins(failed_count, settings):
    # Compare failed login attempts to the system settings' max attempts (3).
    if failed_count >= settings.failed_login_threshold:
        return "too many failed login attempts prior to the transaction"
    return None


def evaluate(transaction_type, amount, location, timestamp, previous, failed_logins, settings):
    checks = [
        check_large_amount(transaction_type, amount, settings),
        check_impossible_travel(location, timestamp, previous, settings),
        check_failed_logins(failed_logins, settings),
    ]
    reasons = []
    for check in checks:
        if check:
            reasons.append(check)
    return reasons  # reasons the transaction was flagged (empty if none)
