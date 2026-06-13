import os
import requests

# =========================
# ENV KEYS
# =========================
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# =========================
# ENDPOINTS (2026)
# =========================
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"

TIMEOUT_SECONDS = 12


# =========================
# GROQ CALL
# =========================
def ask_groq(prompt: str):

    if not GROQ_API_KEY:
        print("Groq API key missing")
        return None

    try:
        response = requests.post(
            GROQ_URL,
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "llama-3.1-8b-instant",  # ✅ Updated model
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.2,
                "max_tokens": 300
            },
            timeout=TIMEOUT_SECONDS
        )

        print("Groq response:", response.status_code)

        if response.status_code != 200:
            print("Groq error:", response.text)
            return None

        return response.json()["choices"][0]["message"]["content"]

    except Exception as e:
        print("Groq exception:", str(e))
        return None


# =========================
# GEMINI CALL
# =========================
def ask_gemini(prompt: str):

    if not GEMINI_API_KEY:
        print("Gemini API key missing")
        return None

    try:
        response = requests.post(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            headers={"Content-Type": "application/json"},
            json={
                "contents": [
                    {
                        "parts": [{"text": prompt}]
                    }
                ]
            },
            timeout=TIMEOUT_SECONDS
        )

        print("Gemini response:", response.status_code)

        if response.status_code != 200:
            print("Gemini error:", response.text)
            return None

        return response.json()["candidates"][0]["content"]["parts"][0]["text"]

    except Exception as e:
        print("Gemini exception:", str(e))
        return None


# =========================
# FAILOVER ROUTER
# =========================
def generate_explanation(signal_data: dict):

    prompt = f"""
Bạn là chuyên gia phân tích giao dịch định lượng.

Hãy giải thích tín hiệu sau (ngắn gọn, 3–4 câu, rõ ràng):

Symbol: {signal_data.get('symbol')}
Pattern: {signal_data.get('pattern')}
Direction: {signal_data.get('direction')}
Regime: {signal_data.get('regime')}
RSI: {signal_data.get('rsi')}
AI Probability: {signal_data.get('prob')}
Risk/Reward: 1:2
"""

    # ✅ Try Groq first
    result = ask_groq(prompt)
    if result:
        return result

    # ✅ Fallback Gemini
    result = ask_gemini(prompt)
    if result:
        return result

    return "⚠️ Hệ thống AI hiện không khả dụng."

def generate_analysis_advice(analysis_data: dict):

    prompt = f"""
Bạn là một chuyên gia giao dịch định lượng sở trường thị trường Coin chuyên nghiệp.
Hãy phân tích dữ liệu dưới đây theo phong cách Quant Risk Analysis.

Không viết dài dòng. Trình bày 8–10 câu rõ ràng, súc tích.

==============================
SYMBOL: {analysis_data.get('symbol')}
TIMEFRAME: {analysis_data.get('timeframe')}

Regime: {analysis_data.get('regime')}
ATR%: {analysis_data.get('atr_pct')}
EMA Distance%: {analysis_data.get('ema_dist_pct')}
Funding Rate: {analysis_data.get('funding_rate')}

LONG Score: {analysis_data.get('long_score')}
SHORT Score: {analysis_data.get('short_score')}

HTF Block LONG: {analysis_data.get('long_htf_block')}
HTF Block SHORT: {analysis_data.get('short_htf_block')}

Funding Block LONG: {analysis_data.get('long_funding_block')}
Funding Block SHORT: {analysis_data.get('short_funding_block')}

Risk Model: Fixed SL with RR 1:2
==============================

Yêu cầu phân tích:

1. So sánh rõ ràng LONG vs SHORT.
2. Xác định thiên hướng (bias) nếu có.
3. Đánh giá mức độ rủi ro dựa trên volatility (ATR%) và block status.
4. Chỉ ra yếu tố có thể làm tín hiệu mất hiệu lực.
5. Không đưa lời khuyên đầu tư tuyệt đối.

Viết theo phong cách chuyên gia định lượng, trung lập, logic.
"""

    result = ask_gemini(prompt)
    
    if result:
        return result
    
    result = ask_groq(prompt)
    if result:
        return result

    

    return "⚠️ AI hiện không khả dụng."