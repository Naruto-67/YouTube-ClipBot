# engine/llm_client.py
import json
import os
import re
import time
from typing import Any, Dict, Optional

from engine.config_manager import config_manager
from engine.database import db
from engine.quota_manager import quota_manager


class LLMClient:
    """
    Unified LLM client that:
    - Selects the best available model automatically (Gemini → Groq → last-resort)
    - Handles JSON parsing and retries on parse failures
    - Tracks reliability metrics in the database
    - Never throws — returns None if all models fail
    """

    def __init__(self):
        self._gemini_client = None
        self._groq_client = None

    # ── Provider clients (lazy init) ──────────────────────────────────────

    def _gemini(self):
        if self._gemini_client is None:
            from google import genai
            self._gemini_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        return self._gemini_client

    def _groq(self):
        if self._groq_client is None:
            from groq import Groq
            self._groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])
        return self._groq_client

    # ── Raw API calls ─────────────────────────────────────────────────────

    def _call_gemini(self, model_name: str, prompt: str, system: str) -> str:
        from google.genai import types
        response = self._gemini().models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=0.3,
                max_output_tokens=2000,
                # Force pure JSON output — eliminates markdown fences and
                # thinking-model preamble that cause parse failures.
                response_mime_type="application/json",
            ),
        )
        return response.text

    def _call_groq(self, model_name: str, prompt: str, system: str) -> str:
        response = self._groq().chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=2000,
        )
        return response.choices[0].message.content

    # ── JSON extraction ───────────────────────────────────────────────────

    def _parse_json(self, text: str) -> Optional[Dict]:
        """
        Extract JSON from AI response. Handles:
        - Pure JSON responses (normal path after response_mime_type fix)
        - JSON wrapped in markdown fences
        - JSON buried inside explanatory / thinking text
        """
        if not text:
            return None

        t = text.strip()

        # Strip markdown fences (```json ... ``` or ``` ... ```)
        if t.startswith("```"):
            t = re.sub(r'^```(?:json)?\s*\n?', '', t)
            t = re.sub(r'\n?```\s*$', '', t)
            t = t.strip()

        # Direct parse — fastest path
        try:
            return json.loads(t)
        except json.JSONDecodeError:
            pass

        # Strip <thinking>…</thinking> blocks (Gemini 2.5 thinking models)
        t_no_think = re.sub(r'<thinking>.*?</thinking>', '', t,
                            flags=re.DOTALL).strip()
        try:
            return json.loads(t_no_think)
        except json.JSONDecodeError:
            pass

        # Find the last (outermost) JSON object or array in the text.
        # We scan from the END so we skip any preamble/thinking text.
        for start_char, end_char in [('{', '}'), ('[', ']')]:
            # Find all candidate start positions, prefer the last one
            positions = [i for i, c in enumerate(t_no_think) if c == start_char]
            for start_pos in reversed(positions):
                depth = 0
                for i, c in enumerate(t_no_think[start_pos:], start_pos):
                    if c == start_char:
                        depth += 1
                    elif c == end_char:
                        depth -= 1
                        if depth == 0:
                            try:
                                return json.loads(t_no_think[start_pos:i + 1])
                            except json.JSONDecodeError:
                                break

        return None

    # ── Public interface ──────────────────────────────────────────────────

    def generate(
        self,
        prompt: str,
        system_prompt: str,
        call_type: str = "general",
        max_retries: int = 2,
    ) -> Optional[Dict]:
        """
        Call the best available AI model and return parsed JSON.
        Automatically falls back through the model chain on failure.
        Returns None if all attempts across all models fail.
        """
        attempted_models = set()

        for attempt in range(max_retries + 1):
            model_info = quota_manager.get_best_available_model()

            if model_info is None:
                print("❌ All AI models exhausted for today.")
                db.log_failure("llm_client", "All models exhausted", call_type)
                return None

            provider, model_name, _ = model_info

            # Skip models we already failed on in this call
            if model_name in attempted_models and attempt < max_retries:
                time.sleep(2)
                continue
            attempted_models.add(model_name)

            # Wait for RPM if needed
            quota_manager.wait_for_rpm_if_needed(provider, model_name)

            try:
                print(f"🤖 [{call_type}] Using {model_name}")

                if provider == "gemini":
                    raw = self._call_gemini(model_name, prompt, system_prompt)
                elif provider == "groq":
                    raw = self._call_groq(model_name, prompt, system_prompt)
                else:
                    continue

                quota_manager.record_model_use(provider, model_name)

                result = self._parse_json(raw)
                if result is None:
                    # Log a snippet of the raw response to aid debugging
                    snippet = (raw or "")[:200].replace("\n", " ")
                    print(f"⚠️  JSON parse failed for {model_name} response. "
                          f"Raw snippet: {snippet!r}")
                    db.log_ai_call(model_name, call_type, False, parse_failed=True)
                    if attempt < max_retries:
                        time.sleep(2 ** attempt)
                        continue
                    return None

                db.log_ai_call(model_name, call_type, True)
                return result

            except Exception as e:
                err_str = str(e)
                is_rate_limit = any(x in err_str.lower() for x in
                                    ["429", "rate limit", "resource exhausted",
                                     "quota", "too many requests"])
                print(f"⚠️  {model_name} error: {err_str[:100]}")
                db.log_ai_call(model_name, call_type, False)

                if is_rate_limit:
                    print(f"🔄 Rate limit hit on {model_name} — escalating to next model")

                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue

        db.log_failure("llm_client", f"All {max_retries + 1} attempts failed", call_type)
        return None


llm_client = LLMClient()
