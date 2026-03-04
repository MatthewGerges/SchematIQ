"""
Quick sanity check: send one prompt to Gemini and print the response.
Run from ChipChat_Project/:  python scripts/test_gemini_api.py
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google import genai

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    print("ERROR: GEMINI_API_KEY not found in .env")
    sys.exit(1)

client = genai.Client(api_key=api_key)

prompt = (
    "You are an electronics design assistant. "
    "List the 5 essential components needed for a USB-C powered BME280 sensor board. "
    "Reply as a JSON array of objects with keys: part, function."
)

print(f"Model:  gemini-2.5-flash")
print(f"Prompt: {prompt[:80]}...")
print("-" * 60)

try:
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    print(response.text)
except Exception as e:
    print(f"ERROR: {e}")
    sys.exit(1)

print("-" * 60)
print("API test passed!")
