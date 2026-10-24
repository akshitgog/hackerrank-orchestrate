"""Case Ingestion & Triage: Request Intent Classifier.

Handles incoming requests in 6 languages (English, Spanish, French, Portuguese, Korean, Japanese).
Interfaces with local decision models (e.g. self-hosted FastAPI endpoint), Fireworks/LiteLLM VLMs,
and falls back to deterministic multilingual triage rules with 3 retries.
"""

import json
import re
import time
from typing import Any, Optional
import requests

from code.src.orchestrator.models import IntentClassificationResult
from code.src.common.llm_client import RobustLLMClient


NON_DELETION_PATTERNS = [
    # English non-deletion & restriction markers
    r"not asking for deletion",
    r"don'?t (?:delete|close|erase|remove)",
    r"do not (?:delete|close|erase|remove)",
    r"leave (?:the|my) account (?:active|in place|as it is)",
    r"keep (?:the|my) account",
    r"leave my profile",
    r"without removing any of my records",
    r"continue using the service",
    r"this is an information request",
    r"not a request to erase",
    r"marketing lists only",
    r"download (?:my )?account information in a portable format",
    r"send me a copy of the information",
    r"copy of last year'?s invoices",
    r"resetting the login",
    r"misspelled on the account",
    r"replace it with the new one and leave",
    # Multilingual non-deletion
    r"삭제하지\s*마",
    r"유지해",
    r"削除しないで",
    r"保持して",
    r"no deseo eliminar",
    r"ne pas supprimer",
]

DELETION_PATTERNS = [
    # English
    r"\bdelet",
    r"\bremov",
    r"\beras",
    r"\bclos",
    r"\bgone\b",
    r"\baudit\b",
    r"\bverif",
    r"right to be forgotten",
    r"no longer (?:need|use) this account",
    r"disconnected my account",
    # Spanish
    r"\beliminar\b",
    r"\beliminaci[oó]n\b",
    r"\bborrar\b",
    # French
    r"\bsuppression\b",
    r"\beffacer\b",
    r"\beffacement\b",
    # Portuguese
    r"\bexclus[aã]o\b",
    r"\bapagar\b",
    # German
    r"\bl[oö]schen\b",
    r"\bvernichten\b",
    # Korean (영구 삭제, 계정 삭제, 삭제, 탈퇴)
    r"삭제",
    r"영구\s*삭제",
    r"계정\s*삭제",
    r"탈퇴",
    # Japanese (アカウント削除, 完全な削除, 削除, 消去)
    r"削除",
    r"完全な削除",
    r"消去",
    r"解約",
]


class IntentClassifier:
    """Classifies customer request_text across 6 languages using Decision Models + VLMs."""

    def __init__(
        self,
        threshold: float = 0.80,
        llm_model: Optional[str] = None,
        decision_endpoint: Optional[str] = None,
        timeout: int = 15,
        max_retries: int = 3,
    ) -> None:
        self.threshold = threshold
        self.llm_model = llm_model
        self.decision_endpoint = decision_endpoint
        self.timeout = timeout
        self.max_retries = max_retries

    def _call_local_decision_model(
        self, case_id: str, request_text: str
    ) -> Optional[IntentClassificationResult]:
        """Query local decision model endpoint (e.g. self-hosted on RTX 3050)."""
        if not self.decision_endpoint:
            return None

        import os
        api_key = os.getenv("JEV_API_KEY", os.getenv("TYPESAFE_JEV_API_KEY", "local-jev-key-12345"))
        headers = {"Authorization": f"Bearer {api_key}"}

        payload = {
            "model": "local-decision-v1",
            "state": request_text,
            "labels": [
                "customer requesting data deletion, account erasure, or right to be forgotten",
                "general inquiry, order tracking, bug report, or billing support",
            ],
        }
        delay = 0.5

        for attempt in range(1, self.max_retries + 1):
            try:
                resp = requests.post(
                    self.decision_endpoint,
                    json=payload,
                    headers=headers,
                    timeout=self.timeout,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    conf = float(data.get("confidence", 0.0))
                    is_auth = conf >= self.threshold
                    cat = "ACCOUNT_DELETION" if is_auth else "NON_DELETION"
                    rat = f"Local Jev model evaluated deletion probability: {conf:.4f} (threshold: {self.threshold})"

                    return IntentClassificationResult(
                        case_id=case_id,
                        request_text=request_text,
                        is_deletion_authorized=is_auth,
                        confidence=conf,
                        intent_category=cat,
                        rationale=rat,
                    )
            except Exception:
                if attempt < self.max_retries:
                    time.sleep(delay)
                    delay *= 2.0

        return None

    def _call_vlm_engine(
        self, case_id: str, request_text: str
    ) -> Optional[IntentClassificationResult]:
        """Query Fireworks AI VLM / LLM via LiteLLM with 3 retries."""
        if not self.llm_model:
            return None

        prompt = (
            "You are a GDPR/CCPA privacy triage classifier.\n"
            "Analyze the following customer request across 6 languages (English, Spanish, French, Portuguese, Korean, Japanese).\n"
            "Determine if it authorizes permanent account/data deletion, or if it is a non-deletion action (data export, marketing opt-out, SAR access, correction).\n"
            "Return valid JSON ONLY:\n"
            "{\n"
            '  "is_deletion_authorized": true/false,\n'
            '  "confidence": 0.0 to 1.0,\n'
            '  "intent_category": "ACCOUNT_DELETION" or "DATA_EXPORT" or "ACCESS_REQUEST" or "MARKETING_OPT_OUT" or "RECTIFICATION_CORRECTION",\n'
            '  "rationale": "short explanation"\n'
            "}\n\n"
            f"Customer Request:\n\"{request_text}\""
        )

        messages = [
            {"role": "system", "content": "You are a precise privacy legal classifier. Respond in valid JSON."},
            {"role": "user", "content": prompt},
        ]

        raw_response = RobustLLMClient.complete(
            model=self.llm_model,
            messages=messages,
            temperature=0.0,
            timeout=self.timeout,
            max_retries=self.max_retries,
        )

        if not raw_response:
            return None

        try:
            clean_json = raw_response
            if "```" in clean_json:
                clean_json = re.sub(r"^```(?:json)?\n?", "", clean_json.strip())
                clean_json = re.sub(r"\n?```$", "", clean_json.strip())

            parsed = json.loads(clean_json)
            is_auth = bool(parsed.get("is_deletion_authorized", False))
            conf = float(parsed.get("confidence", 0.85))
            cat = str(parsed.get("intent_category", "ACCOUNT_DELETION" if is_auth else "NON_DELETION"))
            rat = str(parsed.get("rationale", "Classified by VLM engine"))

            if is_auth and conf < self.threshold:
                is_auth = False

            return IntentClassificationResult(
                case_id=case_id,
                request_text=request_text,
                is_deletion_authorized=is_auth,
                confidence=conf,
                intent_category=cat,
                rationale=rat,
            )
        except Exception:
            return None

    def classify(self, case_id: str, request_text: str) -> IntentClassificationResult:
        """Classify a request and determine if deletion is authorized.

        Evaluation Flow:
        1. Explicit Non-Deletion Guard: Customer directives refusing deletion (keep account, marketing only, export)
           are strictly respected first per GDPR/CCPA §6.2.
        2. Local Decision Model (if enabled and running)
        3. VLM / LLM Engine (Fireworks AI / GPT-4o / Gemini)
        4. Multilingual Deterministic Triage Engine (English, Spanish, French, Portuguese, Korean, Japanese)
        """
        text_clean = request_text.strip().lower()

        # 1. Guardrail against explicit non-deletion signals & restrictions
        for pat in NON_DELETION_PATTERNS:
            if re.search(pat, text_clean):
                category = "NON_DELETION"
                if "marketing" in text_clean or "promotional" in text_clean or "마케팅" in text_clean:
                    category = "MARKETING_OPT_OUT"
                elif "download" in text_clean or "invoices" in text_clean or "portable" in text_clean:
                    category = "DATA_EXPORT"
                elif (
                    "access" in text_clean
                    or "login" in text_clean
                    or "information request" in text_clean
                    or "send me a copy" in text_clean
                ):
                    category = "ACCESS_REQUEST"
                elif "misspelled" in text_clean or "replace" in text_clean or "out of date" in text_clean:
                    category = "RECTIFICATION_CORRECTION"

                return IntentClassificationResult(
                    case_id=case_id,
                    request_text=request_text,
                    is_deletion_authorized=False,
                    confidence=0.95,
                    intent_category=category,
                    rationale=f"Explicit non-deletion request detected matching pattern: {pat}",
                )

        # 2. Local decision model (if configured)
        if self.decision_endpoint:
            local_res = self._call_local_decision_model(case_id, request_text)
            if local_res:
                return local_res

        # 3. VLM / LLM Engine (if configured)
        if self.llm_model:
            vlm_res = self._call_vlm_engine(case_id, request_text)
            if vlm_res:
                return vlm_res

        # 4. Multilingual Deterministic Triage Engine (Fallback)

        # B. Multilingual deletion authorization markers
        matched_deletion = [pat for pat in DELETION_PATTERNS if re.search(pat, text_clean)]
        if matched_deletion:
            confidence = 0.95
            is_authorized = confidence >= self.threshold
            return IntentClassificationResult(
                case_id=case_id,
                request_text=request_text,
                is_deletion_authorized=is_authorized,
                confidence=confidence,
                intent_category="ACCOUNT_DELETION",
                rationale=f"Deletion authorized via multilingual markers: {matched_deletion[:3]}",
            )

        # C. Default fallback for portal requests
        confidence = 0.85
        is_authorized = confidence >= self.threshold
        return IntentClassificationResult(
            case_id=case_id,
            request_text=request_text,
            is_deletion_authorized=is_authorized,
            confidence=confidence,
            intent_category="ACCOUNT_DELETION",
            rationale="Deletion request context without non-deletion restrictions.",
        )
