import os
import json
import google.generativeai as genai

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise RuntimeError("Missing GEMINI_API_KEY")

genai.configure(api_key=api_key)

model = genai.GenerativeModel("gemini-1.5-flash")


def extract_intent_from_text(user_request: str) -> dict:

    prompt = f"""
You are a financial assistant.

Convert the user request into JSON.

Return ONLY valid JSON.

Schema:

{{
    "action": "CREATE_INVOICE",
    "recipient": "user@example.com",
    "target_currency": "USD",
    "item_name": "Keyboard",
    "quantity": 5,
    "source_budget_cap": 500
}}

Request:

{user_request}
"""

    response = model.generate_content(prompt)

    text = response.text.strip()

    if text.startswith("```"):
        text = text.replace("```json", "")
        text = text.replace("```", "")
        text = text.strip()

    return json.loads(text)