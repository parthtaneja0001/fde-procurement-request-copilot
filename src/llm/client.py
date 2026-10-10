from __future__ import annotations

import json
import os
import time
from typing import Any, Type, TypeVar
from pydantic import BaseModel
from dotenv import load_dotenv

from src.llm.mock_llm import generate_mock_procurement_decision

load_dotenv(override=False)

T = TypeVar("T", bound=BaseModel)


class LLMClient:
    def __init__(self, model_name: str | None = None, provider: str | None = None):
        self.mock_mode = os.getenv("MOCK_LLM", "0").lower() in ("1", "true", "yes")
        self.gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.openai_key = os.getenv("OPENAI_API_KEY")

        if provider:
            self.provider = provider.lower()
        elif self.gemini_key:
            self.provider = "gemini"
        elif self.openai_key:
            self.provider = "openai"
        else:
            self.provider = "mock"
            self.mock_mode = True

        self.model_name = model_name or os.getenv(
            "MODEL_NAME",
            "gemini-2.5-flash" if self.provider == "gemini" else "gpt-4o-mini"
        )

    def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        schema_cls: Type[T],
        fallback_context: dict[str, Any] | None = None,
    ) -> tuple[T, int, int]:
        """Generate structured Pydantic output with retry and graceful fallback.
        Returns: (result_model, call_count, estimated_tokens)
        """
        if self.mock_mode or self.provider == "mock":
            # Generate deterministic mock output
            req = fallback_context.get("request", {}) if fallback_context else {}
            tools = fallback_context.get("executed_tools", {}) if fallback_context else {}
            arch = fallback_context.get("architecture", "single") if fallback_context else "single"
            raw_dict = generate_mock_procurement_decision(req, tools, arch)
            parsed = schema_cls.model_validate(raw_dict)
            return parsed, 1, 350

        # Real LLM execution with retry
        call_count = 0
        tokens_est = 0
        last_error = None

        for attempt in range(2):
            call_count += 1
            try:
                raw_json_str, tokens = self._call_provider(system_prompt, user_prompt, schema_cls)
                tokens_est += tokens
                data = json.loads(raw_json_str)
                parsed = schema_cls.model_validate(data)
                return parsed, call_count, tokens_est
            except Exception as ex:
                last_error = ex
                # On retry, augment user prompt with error message
                user_prompt += f"\n\nPREVIOUS ATTEMPT FAILED WITH ERROR: {str(ex)}. Ensure output is strict valid JSON conforming to schema."

        # Fallback to deterministic mock on complete failure
        if fallback_context:
            req = fallback_context.get("request", {})
            tools = fallback_context.get("executed_tools", {})
            arch = fallback_context.get("architecture", "single")
            raw_dict = generate_mock_procurement_decision(req, tools, arch)
            parsed = schema_cls.model_validate(raw_dict)
            return parsed, call_count, tokens_est

        raise RuntimeError(f"LLM generation failed after 2 attempts: {last_error}")

    def _call_provider(self, system_prompt: str, user_prompt: str, schema_cls: Type[T]) -> tuple[str, int]:
        if self.provider == "gemini":
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=self.gemini_key)
            response = client.models.generate_content(
                model=self.model_name,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type="application/json",
                    response_schema=schema_cls,
                    temperature=0.1,
                ),
            )
            tokens = 400
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                tokens = response.usage_metadata.total_token_count or 400
            return response.text, tokens

        elif self.provider == "openai":
            import openai
            client = openai.OpenAI(api_key=self.openai_key)
            response = client.beta.chat.completions.parse(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format=schema_cls,
                temperature=0.1,
            )
            tokens = response.usage.total_tokens if response.usage else 400
            return response.choices[0].message.content, tokens

        raise ValueError(f"Unknown provider '{self.provider}'")
