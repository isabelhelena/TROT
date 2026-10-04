import os
import logging
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

from google import genai
from google.genai import types

load_dotenv()
logger = logging.getLogger("trot.classifier")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()

# Initialize GenAI Client
_client: Optional[genai.Client] = None


def get_genai_client() -> Optional[genai.Client]:
    """Returns singleton Google GenAI client if GEMINI_API_KEY is configured."""
    global _client
    if _client is not None:
        return _client
    if not GEMINI_API_KEY:
        logger.warning("[GEMINI_UNCONFIGURED] GEMINI_API_KEY is not set.")
        return None
    _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


# Tool Declarations for Agentic Defense
NOTIFY_GUARDIAN_TOOL = types.FunctionDeclaration(
    name="notify_guardian",
    description="Alerts the guardian dashboard and sends urgent notifications about a detected scam.",
    parameters_json_schema={
        "type": "object",
        "properties": {
            "scam_type": {
                "type": "string",
                "enum": [
                    "grandchild_in_jail",
                    "bank_fraud",
                    "irs_warrant",
                    "tech_support",
                    "lottery_prize",
                    "other_fraud",
                ],
                "description": "Category of scam identified in the conversation.",
            },
            "severity": {
                "type": "string",
                "enum": ["medium", "high"],
                "description": "Risk level of the ongoing scam attempt.",
            },
            "confidence": {
                "type": "number",
                "description": "Confidence score between 0.0 and 1.0 that this is an active scam.",
            },
            "reason": {
                "type": "string",
                "description": "Clear 1-sentence plain-language explanation of why this was flagged.",
            },
        },
        "required": ["scam_type", "severity", "confidence", "reason"],
    },
)

WARN_SENIOR_TOOL = types.FunctionDeclaration(
    name="warn_senior",
    description="Plays a spoken warning message directly into the call leg to protect the senior.",
    parameters_json_schema={
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "A calm, reassuring spoken warning advising the senior not to send money or share personal info.",
            }
        },
        "required": ["message"],
    },
)

END_CALL_TOOL = types.FunctionDeclaration(
    name="end_call",
    description="Immediately hangs up on the scammer to prevent imminent financial loss or emotional manipulation.",
    parameters_json_schema={
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": "Specific reason requiring immediate call termination.",
            }
        },
        "required": ["reason"],
    },
)

BLOCK_NUMBER_TOOL = types.FunctionDeclaration(
    name="block_number",
    description="Marks the caller's phone number as suspicious across the network to protect all users.",
    parameters_json_schema={
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": "Reason for flagging this caller number network-wide.",
            }
        },
        "required": ["reason"],
    },
)

AGENTIC_DEFENSE_TOOL = types.Tool(
    function_declarations=[
        NOTIFY_GUARDIAN_TOOL,
        WARN_SENIOR_TOOL,
        END_CALL_TOOL,
        BLOCK_NUMBER_TOOL,
    ]
)

SYSTEM_PROMPT = """You are TROT Autonomous Voice Guardian, an AI defense agent protecting vulnerable seniors from live telephone scams in real time.

You are evaluating the recent rolling audio transcript of the CALLER from an ongoing phone call.

RULES:
1. Normal / Benign calls (family conversations, doctor/clinic appointments, deliveries, or benign uses of words like 'shed permit warrant', 'birthday gift card'):
   - DO NOT invoke any defense tools.
   - Simply state why the call appears legitimate.

2. Active Scam Calls (grandparent imposter, fake arrest warrants, IRS/police threats, bank fraud transfers, gift card demands, Bitcoin ATM requests, secrecy demands like 'don't tell anyone'):
   - You MUST invoke proportionate defense tools:
     - notify_guardian: ALWAYS invoke this with scam_type, severity ('medium' or 'high'), confidence (0.0 to 1.0), and a concise reason.
     - warn_senior: Invoke this with a calm warning if the senior is being actively deceived or frightened.
     - end_call: Invoke this IMMEDIATELY if high confidence (>0.80) or severe imminent extortion (arrest, wire transfer, gift cards).
     - block_number: Invoke this to flag the number for the shared network.

3. Be decisive and precise. Distinguish true scams from innocent conversational context."""


def classify_call_transcript(
    transcript_window: str,
    from_number: str,
    network_threat_count: int = 0,
) -> List[Dict[str, Any]]:
    """
    Evaluates rolling transcript text with Gemini 3.5 Flash Lite.
    Returns a list of invoked tool calls (e.g. notify_guardian, end_call).
    """
    client = get_genai_client()
    if not client:
        logger.warning("[CLASSIFY_FALLBACK] Gemini client not available.")
        return []

    # Build prompt context, injecting network reputation if known
    context_prefix = ""
    if network_threat_count > 0:
        context_prefix = (
            f"[COMMUNITY REPUTATION WARNING: Caller {from_number} has been flagged "
            f"{network_threat_count} time(s) across the TROT network for previous scams!]\n\n"
        )

    user_content = (
        f"{context_prefix}"
        f"Caller Number: {from_number}\n"
        f"Recent Caller Audio Transcript (last ~60 seconds):\n\"\"\"\n{transcript_window}\n\"\"\"\n\n"
        f"Evaluate the conversation and invoke any necessary defense tools."
    )

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=user_content,
            config=types.GenerateContentConfig(
                tools=[AGENTIC_DEFENSE_TOOL],
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    disable=True
                ),
                system_instruction=SYSTEM_PROMPT,
                temperature=0.0,
            ),
        )

        tool_calls: List[Dict[str, Any]] = []
        if response.function_calls:
            for call in response.function_calls:
                call_dict = {
                    "name": call.name,
                    "args": dict(call.args) if call.args else {},
                }
                tool_calls.append(call_dict)
                logger.info(
                    f"[GEMINI_TOOL_CALL] Function={call.name} Args={call_dict['args']}"
                )

        if not tool_calls:
            logger.info(
                f"[GEMINI_BENIGN] No threat tools invoked. Verdict: {getattr(response, 'text', 'Benign')[:120]}"
            )

        return tool_calls

    except Exception as e:
        logger.error(
            f"[GEMINI_CLASSIFY_ERROR] Error calling {GEMINI_MODEL}: {e}",
            exc_info=True,
        )
        return []


def generate_call_summary(full_transcript: str) -> str:
    """
    Generates a concise 1-2 sentence plain-language summary of a completed call.
    """
    client = get_genai_client()
    if not client or not full_transcript.strip():
        return "Call completed."

    prompt = (
        "Summarize this phone conversation for a family caregiver in 1 or 2 concise, reassuring sentences. "
        "Highlight who called and the main topic discussed:\n\n"
        f"\"{full_transcript}\""
    )

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction="You write concise, objective summaries of phone calls for elderly family members.",
                temperature=0.2,
                max_output_tokens=150,
            ),
        )
        summary = (response.text or "").strip()
        return summary if summary else "Call completed."
    except Exception as e:
        logger.warning(f"[SUMMARY_ERROR] Failed to generate summary: {e}")
        return "Call completed."
