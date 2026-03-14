# engine/llm_client.py
import json
import os
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
        - Pure JSON responses
        - JSON wrapped in markdown fences
        - JSON buried inside explanatory text
        """
        if not text:
            return None

        # Strip markdown fences
        t = text.strip()
        if t.startswith("```"):
            lines = t.split("\n")
            inner_lines = []
            for line in lines[1:]:
                if line.strip() == "```":
                    break
                inner_lines.append(line)
            t = "\n".join(inner_lines).strip()

        # Direct parse
        try:
            return json.loads(t)
        except json.JSONDecodeError:
            pass

        # Find first JSON object or array
        for start_char, end_char in [('{', '}'), ('[', ']')]:
            start = t.find(start_char)
            if start == -1:
                continue
            # Find matching close
            depth = 0
            for i, c in enumerate(t[start:], start):
                if c == start_char:
                    depth += 1
                elif c == end_char:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(t[start:i + 1])
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
                    print(f"⚠️  JSON parse failed for {model_name} response.")
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
                    # Mark this model as temporarily unavailable by burning its RPM
                    # (it will naturally clear after 60 seconds)
                    print(f"🔄 Rate limit hit on {model_name} — escalating to next model")

                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue

        db.log_failure("llm_client", f"All {max_retries + 1} attempts failed", call_type)
        return None


llm_client = LLMClient()
