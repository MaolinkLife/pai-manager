# core/cognitive_analyzer.py
import json
from typing import Dict, Any, Optional
from openai import OpenAI

from services.logger_service import log_audit_entry, AuditStatus
from services.config_service import get_config_value
from constants.prompts import COGNITIVE_ANALYSIS_PROMPT
from constants.settings import (
    OPENROUTER_BASE_URL,
    DEFAULT_MODEL,
    DEFAULT_TEMPERATURE,
    DEFAULT_MAX_TOKENS,
    DEFAULT_HOST,
    PROJECT_NAME,
)
from services import ollama_service



class CognitiveAnalyzer:
    """
    Cognitive analyzer for detecting emotions, intents,
    risks and recommending response strategies via OpenRouter API.
    """

    def __init__(self):
        # Load configuration from "openrouter" section
        self.model = get_config_value("openrouter.model", DEFAULT_MODEL)
        self.api_key = get_config_value("openrouter.api_key")

        # Log analyzer initialization status
        if not self.api_key:
            log_audit_entry(
                "cognitive_analyzer_init_error",
                "[Cognitive Analyzer] OpenRouter API key not found in configuration (openrouter.api_key).",
                AuditStatus.ERROR,
            )
        else:
            log_audit_entry(
                "cognitive_analyzer_init",
                f"[Cognitive Analyzer] Initialized with model: {self.model}",
                AuditStatus.INFO,
            )

    def is_configured(self) -> bool:
        """Check if analyzer is properly configured (API key exists)."""
        return bool(self.api_key)

    async def analyze(
        self, user_message: str, context: Dict[str, Any] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Analyze user message and return structured JSON.

        Args:
            user_message: User's input message
            context: Optional context (history, visual, etc.)

        Returns:
            Parsed JSON dict with analysis results,
            or None if not configured / error occurred.
        """
        if not self.is_configured():
            log_audit_entry(
                "cognitive_analyzer_skipped",
                "[Cognitive Analyzer] Skipped: API key missing.",
                AuditStatus.INFO,
            )
            return None

        try:
            log_audit_entry(
                "cognitive_analyzer_start",
                "[Cognitive Analyzer] Starting analysis of user message.",
                AuditStatus.INFO,
                details={
                    "message_preview": (
                        user_message[:50] + "..."
                        if len(user_message) > 50
                        else user_message
                    )
                },
            )

            result = self._call_openrouter_api(user_message, context)

            log_audit_entry(
                "cognitive_analyzer_success",
                "[Cognitive Analyzer] Analysis completed successfully.",
                AuditStatus.SUCCESS,
                details={"result_preview": str(result)},
            )

            return result

        except Exception as e:
            if self._is_rate_limited(e):
                log_audit_entry(
                    "cognitive_analyzer_rate_limit",
                    "[Cognitive Analyzer] Rate limit hit; attempting local fallback.",
                    AuditStatus.WARNING,
                    details={"error": str(e)},
                )
                try:
                    result = self._call_local_fallback(user_message, context)
                    log_audit_entry(
                        "cognitive_analyzer_fallback_success",
                        "[Cognitive Analyzer] Local fallback completed successfully.",
                        AuditStatus.SUCCESS,
                        details={"result_preview": str(result)},
                    )
                    return result
                except Exception as fallback_error:
                    log_audit_entry(
                        "cognitive_analyzer_fallback_error",
                        f"[Cognitive Analyzer] Local fallback failed: {fallback_error}",
                        AuditStatus.ERROR,
                        details={
                            "error": str(fallback_error),
                            "error_type": type(fallback_error).__name__,
                        },
                    )
                    return None

            log_audit_entry(
                "cognitive_analyzer_error",
                f"[Cognitive Analyzer] Error during analysis: {e}",
                AuditStatus.ERROR,
                details={"error": str(e), "error_type": type(e).__name__},
            )
            return None

    def _call_openrouter_api(
        self, user_message: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Call OpenRouter API with user message and optional context.
        Returns parsed JSON result.
        """
        if not self.api_key:
            raise ValueError("API key is not configured")

        client = OpenAI(base_url=OPENROUTER_BASE_URL, api_key=self.api_key)

        user_prompt_content = f'User message: "{user_message}"'
        if context:
            user_prompt_content += (
                f"\n\nContext:\n{json.dumps(context, ensure_ascii=False, indent=2)}"
            )

        log_audit_entry(
            "cognitive_analyzer_api_request",
            "[Cognitive Analyzer] Sending request to model.",
            AuditStatus.INFO,
            details={"model": self.model},
        )

        completion = client.chat.completions.create(
            extra_headers={
                "HTTP-Referer": DEFAULT_HOST,
                "X-Title": PROJECT_NAME,
            },
            model=self.model,
            messages=[
                {"role": "system", "content": COGNITIVE_ANALYSIS_PROMPT},
                {"role": "user", "content": user_prompt_content},
            ],
            temperature=DEFAULT_TEMPERATURE,
            max_tokens=DEFAULT_MAX_TOKENS,
            response_format={"type": "json_object"},
        )

        response_content = completion.choices[0].message.content

        if not response_content or not response_content.strip():
            raise ValueError("OpenRouter API returned empty response.")

        result = json.loads(response_content)

        log_audit_entry(
            "cognitive_analyzer_call_success",
            "[Cognitive Analyzer] OpenRouter API call successful.",
            AuditStatus.SUCCESS,
            details={"result_type": type(result).__name__},
        )

        return result

    def _is_rate_limited(self, error: Exception) -> bool:
        message = str(error).lower()
        return "rate limit" in message or "429" in message

    def _call_local_fallback(
        self, user_message: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        user_prompt_content = f'User message: "{user_message}"'
        if context:
            user_prompt_content += (
                f"\n\nContext:\n{json.dumps(context, ensure_ascii=False, indent=2)}"
            )

        history = [
            {"role": "system", "content": COGNITIVE_ANALYSIS_PROMPT},
            {"role": "user", "content": user_prompt_content},
        ]

        options = {
            "temperature": DEFAULT_TEMPERATURE,
            "max_tokens": DEFAULT_MAX_TOKENS,
        }

        log_audit_entry(
            "cognitive_analyzer_fallback_request",
            "[Cognitive Analyzer] Sending request to local model.",
            AuditStatus.INFO,
        )

        response = ollama_service.api_standard(history, options)
        assistant_content = (
            response.get("message", {}).get("content", "")
            if isinstance(response, dict)
            else ""
        )

        if not assistant_content.strip():
            raise ValueError("Local fallback returned empty response.")

        try:
            return json.loads(assistant_content)
        except json.JSONDecodeError as decode_error:
            raise ValueError(
                f"Local fallback produced non-JSON response: {assistant_content}"
            ) from decode_error


# Global singleton instance
cognitive_analyzer = CognitiveAnalyzer()
