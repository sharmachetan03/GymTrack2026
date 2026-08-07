import base64
import datetime
import json
import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from garminconnect import Garmin

load_dotenv()

# 1. Load account credentials and Base64 tokens from environment variables / secrets
GARMIN_EMAIL = os.getenv("GARMIN_EMAIL", "")
GARMIN_PASSWORD = os.getenv("GARMIN_PASSWORD", "")
GARMIN_TOKENS_B64 = os.getenv("GARMIN_TOKENS_B64", "")

# Directory where session tokens will be stored on the execution runner
TOKEN_DIR = os.path.expanduser("~/.garminconnect")


def restore_tokens_from_env():
    """
    Decodes GARMIN_TOKENS_B64 secret into ~/.garminconnect/garmin_tokens.json
    This bypasses Garmin's Cloudflare login screen & CAPTCHA on GitHub Actions.
    """
    if GARMIN_TOKENS_B64:
        os.makedirs(TOKEN_DIR, exist_ok=True)
        token_file = os.path.join(TOKEN_DIR, "garmin_tokens.json")
        try:
            decoded_bytes = base64.b64decode(GARMIN_TOKENS_B64.strip())
            with open(token_file, "wb") as f:
                f.write(decoded_bytes)
            print("Successfully restored pre-authenticated session tokens from GARMIN_TOKENS_B64 secret!")
        except Exception as err:
            print(f"Warning: Failed to decode GARMIN_TOKENS_B64 secret: {err}")


def _coerce_numeric(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _extract_spo2_value(payload):
    if payload is None:
        return None

    if isinstance(payload, dict):
        for key in (
            "averageSpo2",
            "avgSpo2",
            "spo2",
            "spO2",
            "value",
            "percentage",
            "pulseOx",
            "pulseOxPercentage",
            "latestSpo2",
            "latestSpO2",
        ):
            numeric_value = _coerce_numeric(payload.get(key))
            if numeric_value is not None:
                return numeric_value

        for nested_value in payload.values():
            if isinstance(nested_value, (dict, list)):
                nested_result = _extract_spo2_value(nested_value)
                if nested_result is not None:
                    return nested_result
        return None

    if isinstance(payload, list):
        for item in reversed(payload):
            extracted_value = _extract_spo2_value(item)
            if extracted_value is not None:
                return extracted_value
        return None

    return _coerce_numeric(payload)


def fetch_my_fitness_data():
    try:
        # Step A: Restore tokens if running in GitHub Actions with secret
        restore_tokens_from_env()

        print("Logging into Garmin Connect using token caching...")
        os.makedirs(TOKEN_DIR, exist_ok=True)

        # Initialize Garmin client with token store
        client = Garmin(GARMIN_EMAIL, GARMIN_PASSWORD)
        client.login(TOKEN_DIR)

        # Get today's current date format (YYYY-MM-DD)
        today = datetime.date.today().isoformat()

        print(f"Fetching statistics for date: {today}...")
        stats = client.get_stats(today)
        summary = client.get_user_summary(today)

        # Convert distance meters to kilometers (fall back to 0 if no distance yet)
        distance_meters = _coerce_numeric(stats.get("totalDistanceMeters")) or 0
        distance_km = round(distance_meters / 1000, 2)

        resting_hr = "--"
        max_hr = "--"
        spo2 = "--"

        # Safe extraction for Heart Rate Range
        try:
            heart_rates = client.get_heart_rates(today)
            if isinstance(heart_rates, dict):
                resting_hr = heart_rates.get("restingHeartRate", "--")
                max_hr = heart_rates.get("maxHeartRate", "--")
        except Exception as hr_error:
            print(f"Heart rate sync error encountered: {hr_error}")

        # Safe recursive extraction for SpO2 Pulse Ox Data
        try:
            spo2_data = client.get_spo2_data(today)
            spo2_value = _extract_spo2_value(spo2_data)
            if spo2_value is None:
                summary_spo2 = _extract_spo2_value(summary)
                if summary_spo2 is not None:
                    spo2 = summary_spo2
                else:
                    spo2 = "--"
            else:
                spo2 = spo2_value
        except Exception as spo2_error:
            print(f"SpO2 sync error encountered: {spo2_error}")

        # Format local Indian Standard Time (IST) timestamp
        ist_now = datetime.datetime.now(ZoneInfo("Asia/Kolkata"))
        timestamp = ist_now.strftime("%b %d, %Y %I:%M %p")

        # Construct exact JSON data structure required by index.html & Botpress KB
        data = {
            "steps": summary.get("totalSteps", 0),
            "calories": int(stats.get("activeKilocalories", 0)),
            "distance_km": distance_km,
            "restingHR": resting_hr,
            "maxHR": max_hr,
            "spo2": spo2,
            "last_updated": timestamp,
        }

        # Write out payload to fitness_data.json
        with open("fitness_data.json", "w") as f:
            json.dump(data, f, indent=4)

        print("Successfully synced steps, calories, heart rate, distance, and SpO2 to fitness_data.json!")

    except Exception as e:
        print(f"Sync error encountered: {e}")


if __name__ == "__main__":
    fetch_my_fitness_data()
