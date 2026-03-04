"""
Quick sanity check: send one prompt to Gemini and print the response.
Run from ChipChat_Project/:  python scripts/test_gemini_api.py
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv  # pip install python-dotenv
from google import genai  # pip install google-genai

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    print("ERROR: GEMINI_API_KEY not found in .env")
    sys.exit(1)

client = genai.Client(api_key=api_key)

# Change this to swap models. Full list: https://ai.google.dev/gemini-api/docs/models
#
# Gemini 3 family (preview):
#   "gemini-3.1-pro"          - advanced intelligence, complex problem-solving, agentic coding
#   "gemini-3-flash"          - frontier-class performance at a fraction of the cost
#   "gemini-3.1-flash-lite"   - frontier-class, fraction of cost (newest)
#   "gemini-3-pro"            - DEPRECATED (shutting down Mar 9, 2026) → use gemini-3.1-pro
#
# Gemini 2.5 family (stable):
#   "gemini-2.5-flash"        - best price-performance, low-latency, reasoning
#   "gemini-2.5-flash-lite"   - fastest and cheapest multimodal in 2.5 family
#   "gemini-2.5-pro"          - most advanced, deep reasoning and coding
#
# Gemini 2.0 family (deprecated):
#   "gemini-2.0-flash"        - DEPRECATED → use gemini-2.5-flash
#   "gemini-2.0-flash-lite"   - DEPRECATED → use gemini-2.5-flash-lite
MODEL = "gemini-2.5-flash"

prompt = (
    "You are an electronics design assistant. "
    "List the essential components needed for a USB-C powered BME280 sensor board. "
    "Reply as a JSON array of objects with keys: part name, manufacturer part number, function."
)

print(f"Model:  {MODEL}")
print(f"Prompt: {prompt[:80]}...")
print("-" * 60)

try:
    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
    )
    print(response.text)
except Exception as e:
    print(f"ERROR: {e}")
    sys.exit(1)

print("-" * 60)
print("API test passed!")
