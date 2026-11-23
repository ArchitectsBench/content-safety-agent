"""
Register the content_safety_ner_analyst agent in Azure AI Foundry.

Run once to create/update the agent definition in the portal:
    python agent.py

The agent will appear under Agents in https://ai.azure.com after this script completes.
"""

import os
import pathlib

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import FunctionTool, PromptAgentDefinition
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

load_dotenv()

PROJECT_ENDPOINT = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
MODEL_DEPLOYMENT = os.environ.get("MODEL_DEPLOYMENT_NAME", "gpt-4o")

AGENT_NAME = "content-safety-ner-analyst"
INSTRUCTIONS_PATH = pathlib.Path(__file__).parent / "instructions.md"


def build_tools() -> list:
    """Return the FunctionTool definitions for Content Safety operations."""

    analyze_text_tool = FunctionTool(
        name="analyze_text_safety",
        description=(
            "Analyze text for harmful content across 4 categories: Hate, Sexual, "
            "Violence, SelfHarm. Returns severity scores and a safety verdict."
        ),
        parameters={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The text content to analyze for safety",
                }
            },
            "required": ["text"],
            "additionalProperties": False,
        },
        strict=True,
    )

    shield_prompt_tool = FunctionTool(
        name="shield_prompt",
        description=(
            "Detect jailbreak attempts and prompt injection attacks in user prompts. "
            "Optionally checks documents for indirect prompt injection."
        ),
        parameters={
            "type": "object",
            "properties": {
                "user_prompt": {
                    "type": "string",
                    "description": "The user prompt to check for jailbreak/injection attacks",
                },
                "documents": {
                    "type": "string",
                    "description": (
                        "Optional: pipe-separated list of document texts to check for "
                        "indirect prompt injection. Leave empty string if none."
                    ),
                },
            },
            "required": ["user_prompt", "documents"],
            "additionalProperties": False,
        },
        strict=True,
    )

    detect_groundedness_tool = FunctionTool(
        name="detect_groundedness",
        description=(
            "Check if an AI-generated response is grounded in the provided source "
            "documents. Detects hallucinations and unsupported claims."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The original user query",
                },
                "ai_response": {
                    "type": "string",
                    "description": "The AI-generated response to verify",
                },
                "grounding_sources": {
                    "type": "string",
                    "description": (
                        "The source/reference documents that the AI response "
                        "should be grounded in"
                    ),
                },
            },
            "required": ["query", "ai_response", "grounding_sources"],
            "additionalProperties": False,
        },
        strict=True,
    )

    detect_protected_material_tool = FunctionTool(
        name="detect_protected_material",
        description=(
            "Detect protected/copyrighted material in text (song lyrics, articles, "
            "recipes, web content) and/or source code matching public repositories. "
            "Pass the natural-language text in 'text' and/or source code in 'code'."
        ),
        parameters={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": (
                        "Natural-language text to check for copyrighted material. "
                        "Empty string to skip the text check."
                    ),
                },
                "code": {
                    "type": "string",
                    "description": (
                        "Source code to check against public repositories. "
                        "Empty string to skip the code check."
                    ),
                },
            },
            "required": ["text", "code"],
            "additionalProperties": False,
        },
        strict=True,
    )

    return [
        analyze_text_tool,
        shield_prompt_tool,
        detect_groundedness_tool,
        detect_protected_material_tool,
    ]


def main() -> None:
    instructions = INSTRUCTIONS_PATH.read_text(encoding="utf-8")

    project = AIProjectClient(
        endpoint=PROJECT_ENDPOINT,
        credential=DefaultAzureCredential(),
    )

    tools = build_tools()

    print(f"Registering agent '{AGENT_NAME}' in Foundry project …")
    agent = project.agents.create_version(
        agent_name=AGENT_NAME,
        definition=PromptAgentDefinition(
            model=MODEL_DEPLOYMENT,
            instructions=instructions,
            tools=tools,
        ),
    )

    print(
        f"\nAgent registered successfully!\n"
        f"  Name:    {agent.name}\n"
        f"  Version: {agent.version}\n"
        f"\nNext steps:\n"
        f"  1. Go to https://ai.azure.com\n"
        f"  2. Open your project\n"
        f"  3. Navigate to Agents section\n"
        f"  4. Find \"{AGENT_NAME}\" and open the playground\n"
        f"  5. Test with sample messages from README.md\n"
    )


if __name__ == "__main__":
    main()
