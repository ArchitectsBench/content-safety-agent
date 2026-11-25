"""
Content Safety tool implementations for the content_safety_ner_analyst agent.

All four functions return JSON strings so the agent can parse them directly.
Auth uses DefaultAzureCredential — no API keys needed.
"""

import json
import os

import requests
from azure.ai.contentsafety import ContentSafetyClient
from azure.ai.contentsafety.models import AnalyzeTextOptions, TextCategory
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

load_dotenv()

CONTENT_SAFETY_ENDPOINT = os.environ.get("CONTENT_SAFETY_ENDPOINT", "")

# Severity threshold: anything above this is considered unsafe
SAFE_SEVERITY_THRESHOLD = 2


def _get_bearer_token() -> str:
    """Obtain a bearer token for the Cognitive Services scope."""
    credential = DefaultAzureCredential()
    return credential.get_token("https://cognitiveservices.azure.com/.default").token


def analyze_text_safety(text: str) -> str:
    """
    Analyze text for harmful content across four categories using the
    azure-ai-contentsafety SDK.

    Args:
        text: The text content to analyze for safety.

    Returns:
        JSON string with category severities, flagged categories, and a verdict.
    """
    try:
        credential = DefaultAzureCredential()
        client = ContentSafetyClient(CONTENT_SAFETY_ENDPOINT, credential)

        request = AnalyzeTextOptions(
            text=text,
            categories=[
                TextCategory.HATE,
                TextCategory.SEXUAL,
                TextCategory.VIOLENCE,
                TextCategory.SELF_HARM,
            ],
        )
        response = client.analyze_text(request)

        categories = []
        flagged = []
        max_severity = 0

        for item in response.categories_analysis:
            severity = item.severity or 0
            categories.append({"category": item.category, "severity": severity})
            if severity > SAFE_SEVERITY_THRESHOLD:
                flagged.append(item.category)
            if severity > max_severity:
                max_severity = severity

        is_safe = len(flagged) == 0

        if is_safe:
            verdict = "SAFE: No harmful content detected across all categories."
        else:
            flagged_str = ", ".join(flagged)
            verdict = (
                f"BLOCKED: {flagged_str} detected at severity {max_severity}/6. "
                f"Content violates safety policy."
            )

        return json.dumps(
            {
                "tool": "analyze_text",
                "is_safe": is_safe,
                "categories": categories,
                "flagged_categories": flagged,
                "max_severity": max_severity,
                "verdict": verdict,
            }
        )

    except Exception as exc:
        return json.dumps(
            {
                "tool": "analyze_text",
                "error": str(exc),
                "verdict": "ERROR: Could not complete text safety analysis.",
            }
        )


def shield_prompt(user_prompt: str, documents: str = "") -> str:
    """
    Detect jailbreak attempts and prompt injection via the REST shieldPrompt API.

    The Python SDK does not expose this endpoint, so we call REST directly with
    a bearer token obtained from DefaultAzureCredential.

    Args:
        user_prompt: The user prompt to check for jailbreak/injection attacks.
        documents: Optional pipe-separated document texts to check for indirect
                   prompt injection. Pass empty string if none.

    Returns:
        JSON string with attack detection results and a verdict.
    """
    try:
        token = _get_bearer_token()

        # Split pipe-separated docs into a list; drop empties
        doc_list = [d.strip() for d in documents.split("|") if d.strip()] if documents else []

        url = (
            f"{CONTENT_SAFETY_ENDPOINT.rstrip('/')}"
            "/contentsafety/text:shieldPrompt?api-version=2024-09-01"
        )
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        body = {"userPrompt": user_prompt, "documents": doc_list}

        resp = requests.post(url, headers=headers, json=body, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        # API returns attackDetected at the top level and per-document results
        user_attack = data.get("userPromptAnalysis", {}).get("attackDetected", False)
        doc_attack = any(
            d.get("attackDetected", False)
            for d in data.get("documentsAnalysis", [])
        )

        if user_attack:
            verdict = (
                "BLOCKED: Jailbreak attempt detected. The prompt contains instructions "
                "attempting to override system safety guidelines."
            )
        elif doc_attack:
            verdict = (
                "BLOCKED: Indirect prompt injection detected in provided documents. "
                "The documents contain instructions attempting to hijack the AI."
            )
        else:
            verdict = "SAFE: No prompt injection or jailbreak attempts detected."

        return json.dumps(
            {
                "tool": "shield_prompt",
                "user_prompt_attack_detected": user_attack,
                "document_attack_detected": doc_attack,
                "verdict": verdict,
            }
        )

    except Exception as exc:
        return json.dumps(
            {
                "tool": "shield_prompt",
                "error": str(exc),
                "verdict": "ERROR: Could not complete prompt shield analysis.",
            }
        )


def detect_groundedness(query: str, ai_response: str, grounding_sources: str) -> str:
    """
    Check whether an AI-generated response is grounded in provided source documents
    using the REST detectGroundedness API.

    Args:
        query: The original user query.
        ai_response: The AI-generated response to verify for hallucinations.
        grounding_sources: The source/reference text the AI response should be based on.

    Returns:
        JSON string with groundedness result, ungrounded percentage, and a verdict.
    """
    try:
        token = _get_bearer_token()

        url = (
            f"{CONTENT_SAFETY_ENDPOINT.rstrip('/')}"
            "/contentsafety/text:detectGroundedness?api-version=2024-09-15-preview"
        )
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        body = {
            "domain": "Generic",
            "task": "QnA",
            "qna": {"query": query},
            "text": ai_response,
            "groundingSources": [grounding_sources],
            "reasoning": False,
        }

        resp = requests.post(url, headers=headers, json=body, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        ungrounded_pct = data.get("ungroundedPercentage", 0.0)
        ungrounded_details_raw = data.get("ungroundedDetails", [])

        # Normalise details to a flat list of strings
        ungrounded_details = []
        for item in ungrounded_details_raw:
            if isinstance(item, dict):
                ungrounded_details.append(item.get("text", str(item)))
            else:
                ungrounded_details.append(str(item))

        is_grounded = not data.get("ungroundedDetected", False)

        if is_grounded:
            verdict = "GROUNDED: The AI response is fully supported by the provided source documents."
        else:
            verdict = (
                "FLAGGED: AI response contains claims not supported by source documents. "
                "This may be a hallucination."
            )

        return json.dumps(
            {
                "tool": "detect_groundedness",
                "is_grounded": is_grounded,
                "ungrounded_percentage": ungrounded_pct,
                "ungrounded_details": ungrounded_details,
                "verdict": verdict,
            }
        )

    except Exception as exc:
        return json.dumps(
            {
                "tool": "detect_groundedness",
                "error": str(exc),
                "verdict": "ERROR: Could not complete groundedness detection.",
            }
        )


def detect_protected_material(text: str = "", code: str = "") -> str:
    """
    Detect protected (copyrighted) material in text and/or source code via the
    REST detectProtectedMaterial APIs. Flags content that matches known
    copyrighted text (song lyrics, articles, recipes, web content) or code that
    matches public GitHub repositories.

    The Python SDK does not expose these endpoints, so we call REST directly with
    a bearer token obtained from DefaultAzureCredential.

    Args:
        text: Natural-language text to check for protected/copyrighted material.
              Pass an empty string to skip the text check.
        code: Source code to check against public repositories. Pass an empty
              string to skip the code check.

    Returns:
        JSON string with per-modality detection flags, any code citations, and a
        verdict.
    """
    try:
        token = _get_bearer_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        base = CONTENT_SAFETY_ENDPOINT.rstrip("/")

        text_detected = False
        code_detected = False
        citations: list = []

        # ── Protected text (GA api-version) ──────────────────────────────────
        if text and text.strip():
            url = f"{base}/contentsafety/text:detectProtectedMaterial?api-version=2024-09-01"
            resp = requests.post(url, headers=headers, json={"text": text}, timeout=30)
            resp.raise_for_status()
            analysis = resp.json().get("protectedMaterialAnalysis", {})
            text_detected = analysis.get("detected", False)

        # ── Protected code (preview api-version) ─────────────────────────────
        if code and code.strip():
            url = (
                f"{base}/contentsafety/text:detectProtectedMaterialForCode"
                "?api-version=2024-09-15-preview"
            )
            resp = requests.post(url, headers=headers, json={"code": code}, timeout=30)
            resp.raise_for_status()
            analysis = resp.json().get("protectedMaterialAnalysis", {})
            code_detected = analysis.get("detected", False)
            for c in analysis.get("codeCitations", []):
                citations.append(
                    {
                        "license": c.get("license", "unknown"),
                        "source_urls": c.get("sourceUrls", []),
                    }
                )

        if not (text or code) or (not text.strip() and not code.strip()):
            verdict = "SKIPPED: No text or code provided to check for protected material."
        elif text_detected or code_detected:
            hits = []
            if text_detected:
                hits.append("copyrighted text")
            if code_detected:
                hits.append("code matching public repositories")
            verdict = (
                f"FLAGGED: Protected material detected ({', '.join(hits)}). "
                f"This content may be subject to copyright/licensing restrictions."
            )
        else:
            verdict = "SAFE: No protected or copyrighted material detected."

        return json.dumps(
            {
                "tool": "detect_protected_material",
                "text_detected": text_detected,
                "code_detected": code_detected,
                "citations": citations,
                "verdict": verdict,
            }
        )

    except Exception as exc:
        return json.dumps(
            {
                "tool": "detect_protected_material",
                "error": str(exc),
                "verdict": "ERROR: Could not complete protected material detection.",
            }
        )
