from app.services.llm_router import (
    generate_explanation,
    generate_analysis_advice
)

# =========================
# TEST DATA 1
# =========================
signal_data = {
    "symbol": "BTCUSDT",
    "pattern": "Bullish Engulfing",
    "direction": "LONG",
    "regime": "Trending",
    "rsi": 62,
    "prob": 0.78
}

# =========================
# TEST DATA 2
# =========================
analysis_data = {
    "symbol": "ETHUSDT",
    "timeframe": "4H",
    "regime": "Volatile",
    "atr_pct": 3.2,
    "ema_dist_pct": 1.8,
    "funding_rate": 0.012,

    "long_score": 7.5,
    "short_score": 5.2,

    "long_htf_block": False,
    "short_htf_block": True,

    "long_funding_block": False,
    "short_funding_block": False
}


print("\n============================")
print("TEST: generate_explanation")
print("============================\n")

result1 = generate_explanation(signal_data)
print(result1)

print("\n============================")
print("TEST: generate_analysis_advice")
print("============================\n")

result2 = generate_analysis_advice(analysis_data)
print(result2)
"""
import requests

# =========================
# DÁN API KEY VÀO ĐÂY
# =========================
#API_KEY = ""
API_KEY = ""


# =========================
# MODEL TEST
# =========================
MODEL = "gemini-2.5-flash"

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


# =========================
# DEBUG KEY
# =========================
def debug_key():
    print("===== API KEY DEBUG =====")

    if not API_KEY:
        print("❌ API key is EMPTY")
        return False

    print("Key length:", len(API_KEY))
    print("Key starts with:", API_KEY[:6])

    if API_KEY.startswith("AIza"):
        print("✅ Key format looks correct (Gemini key)")
    else:
        print("❌ Key format suspicious (should start with AIza)")

    print("==========================\n")
    return True


# =========================
# LIST MODELS
# =========================
def list_models():
    print("===== LIST MODELS =====")

    r = requests.get(
        f"{BASE_URL}",
        params={"key": API_KEY}
    )

    print("Status:", r.status_code)

    if r.status_code != 200:
        print("Error:", r.text)
        return

    data = r.json()
    print("Total models returned:", len(data.get("models", [])))

    for m in data.get("models", [])[:10]:
        print(" -", m["name"])

    print("=========================\n")


# =========================
# TEST GENERATE CONTENT
# =========================
def test_generate():
    print(f"===== TEST generateContent ({MODEL}) =====")

    url = f"{BASE_URL}/{MODEL}:generateContent"

    r = requests.post(
        url,
        params={"key": API_KEY},
        json={
            "contents": [
                {
                    "parts": [{"text": "Say hello in one sentence."}]
                }
            ]
        }
    )

    print("Status:", r.status_code)

    if r.status_code != 200:
        print("Error response:")
        print(r.text)
        return

    data = r.json()

    if "candidates" in data:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        print("✅ SUCCESS")
        print("Response:", text)
    else:
        print("⚠ Unexpected response format:")
        print(data)

    print("=========================\n")


# =========================
# MAIN
# =========================
if __name__ == "__main__":
    if debug_key():
        list_models()
        test_generate()
        """