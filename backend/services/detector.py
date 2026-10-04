import re
import time
import asyncio
import logging
from typing import Dict, List, Tuple, Optional, Any

from backend.db import (
    get_caller_number_record,
    get_network_threat_count,
)
from backend.services.classifier import classify_call_transcript
from backend.services.alerts import (
    record_scam_alert,
    end_active_call,
    play_warning_to_senior,
)

logger = logging.getLogger("trot.detector")

# Word-boundary regex for red-flag keywords
KEYWORD_PATTERN = re.compile(
    r"\b("
    r"gift\s+card|"
    r"warrant|"
    r"wire\s+transfer|"
    r"bitcoin|"
    r"crypto|"
    r"arrest|"
    r"social\s+security|"
    r"don't\s+tell\s+anyone|"
    r"irs|"
    r"internal\s+revenue|"
    r"federal\s+agent|"
    r"jail|"
    r"bail|"
    r"target\s+card|"
    r"apple\s+card"
    r")\b",
    re.IGNORECASE,
)

WINDOW_SECONDS = 60.0
HEARTBEAT_INTERVAL_SECONDS = 20.0
MIN_WORDS_FOR_KEYWORD_TRIGGER = 15


class CallBuffer:
    """Manages the in-memory rolling transcript and detection state for a call."""

    def __init__(
        self,
        call_sid: str,
        senior_id: str,
        guardian_id: str,
        from_number: str,
    ):
        self.call_sid = call_sid
        self.senior_id = senior_id
        self.guardian_id = guardian_id
        self.from_number = from_number

        self.utterances: List[Tuple[float, str]] = []  # (timestamp, text)
        self.last_analyzed_index: int = 0
        self.alert_fired: bool = False
        self.is_active: bool = True
        self.lock = asyncio.Lock()
        self.heartbeat_task: Optional[asyncio.Task] = None

    def append(self, text: str) -> None:
        """Appends a new transcript utterance with timestamp."""
        now = time.time()
        self.utterances.append((now, text))
        self._prune(now)

    def _prune(self, now: float) -> None:
        """Keeps utterances within the rolling 60-second window."""
        cutoff = now - WINDOW_SECONDS
        self.utterances = [u for u in self.utterances if u[0] >= cutoff]

    def get_window_text(self) -> str:
        """Returns joined utterances within the current rolling window."""
        self._prune(time.time())
        return " ".join(u[1] for u in self.utterances).strip()

    def get_word_count(self) -> int:
        """Counts words in the current window."""
        return len(self.get_window_text().split())

    def has_new_text_since_last_analysis(self) -> bool:
        """Checks if new utterances arrived since last check."""
        return len(self.utterances) > self.last_analyzed_index

    def mark_analyzed(self) -> None:
        """Updates the analyzed pointer."""
        self.last_analyzed_index = len(self.utterances)


# Active detectors keyed by call_sid
_active_buffers: Dict[str, CallBuffer] = {}


def get_call_buffer(call_sid: str) -> Optional[CallBuffer]:
    """Retrieves active buffer for a call."""
    return _active_buffers.get(call_sid)


def start_detector(
    call_sid: str,
    senior_id: str,
    guardian_id: str,
    from_number: str,
) -> CallBuffer:
    """Initializes detector and spawns the 20s heartbeat task."""
    if call_sid in _active_buffers:
        return _active_buffers[call_sid]

    buf = CallBuffer(
        call_sid=call_sid,
        senior_id=senior_id,
        guardian_id=guardian_id,
        from_number=from_number,
    )
    _active_buffers[call_sid] = buf

    # Spawn 20-second heartbeat loop
    buf.heartbeat_task = asyncio.create_task(_heartbeat_loop(buf))
    logger.info(f"[DETECTOR_STARTED] CallSid={call_sid} Heartbeat active")
    return buf


async def stop_detector(call_sid: str) -> None:
    """Cancels heartbeat and cleans up memory buffer for a call."""
    buf = _active_buffers.pop(call_sid, None)
    if buf:
        buf.is_active = False
        if buf.heartbeat_task and not buf.heartbeat_task.done():
            buf.heartbeat_task.cancel()
        logger.info(f"[DETECTOR_STOPPED] CallSid={call_sid}")


async def ingest_transcript(call_sid: str, text: str) -> None:
    """
    Called whenever a final utterance is produced by STT.
    Appends to buffer and tests keyword trigger.
    """
    buf = _active_buffers.get(call_sid)
    if not buf or not buf.is_active:
        return

    buf.append(text)

    # If an alert already fired for this call, skip further triggers
    if buf.alert_fired:
        return

    # Trigger 1: Keyword Path (Immediate regex check)
    match = KEYWORD_PATTERN.search(text)
    if match:
        word_count = buf.get_word_count()
        logger.info(
            f"[KEYWORD_HIT] CallSid={call_sid} Matched='{match.group(0)}' (WindowWords={word_count})"
        )
        if word_count >= MIN_WORDS_FOR_KEYWORD_TRIGGER:
            await _run_detection_cycle(buf, trigger="keyword")
        else:
            logger.info(
                f"[KEYWORD_DEFERRED] CallSid={call_sid} Need at least {MIN_WORDS_FOR_KEYWORD_TRIGGER} words before LLM call"
            )


async def _heartbeat_loop(buf: CallBuffer) -> None:
    """Trigger 2: Heartbeat Path (checks every 20s if new text arrived)."""
    try:
        while buf.is_active:
            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
            if not buf.is_active or buf.alert_fired:
                break

            if buf.has_new_text_since_last_analysis():
                logger.info(
                    f"[HEARTBEAT_TRIGGER] CallSid={buf.call_sid} New utterances detected"
                )
                await _run_detection_cycle(buf, trigger="heartbeat")

    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(
            f"[HEARTBEAT_ERROR] CallSid={buf.call_sid}: {e}", exc_info=True
        )


async def _run_detection_cycle(buf: CallBuffer, trigger: str) -> None:
    """
    Executes a Gemini evaluation cycle under a concurrency lock.
    Enforces in-progress gating, trusted-number checks, and autonomous tool calling.
    """
    if buf.alert_fired or not buf.is_active:
        return

    async with buf.lock:
        if buf.alert_fired or not buf.is_active:
            return

        from backend.main import get_active_call_status

        # 1. In-Progress Gating: Only analyze when senior has answered
        status = get_active_call_status(buf.call_sid)
        if status != "in_progress":
            logger.info(
                f"[DETECTION_GATED] CallSid={buf.call_sid} Status='{status}' (not in_progress)"
            )
            return

        # 2. Trusted Number Check: Skip if explicitly marked trusted
        caller_rec = get_caller_number_record(buf.senior_id, buf.from_number)
        if caller_rec and caller_rec.get("status") == "trusted":
            logger.info(
                f"[DETECTION_SKIPPED] CallSid={buf.call_sid} Caller {buf.from_number} is trusted"
            )
            return

        # 3. Community Reputation Context: Query network-wide threat count
        threat_count = get_network_threat_count(buf.from_number)

        transcript_window = buf.get_window_text()
        if not transcript_window:
            return

        buf.mark_analyzed()

        logger.info(
            f"[RUNNING_GEMINI] CallSid={buf.call_sid} Trigger={trigger} Words={len(transcript_window.split())}"
        )

        # 4. Invoke Gemini 3.5 Flash Lite
        tool_calls = await asyncio.to_thread(
            classify_call_transcript,
            transcript_window=transcript_window,
            from_number=buf.from_number,
            network_threat_count=threat_count,
        )

        # 5. Execute Autonomous Defense Tools
        if tool_calls:
            for tool in tool_calls:
                name = tool.get("name")
                args = tool.get("args", {})

                if name == "notify_guardian":
                    scam_type = args.get("scam_type", "other_fraud")
                    severity = args.get("severity", "high")
                    confidence = float(args.get("confidence", 0.9))
                    reason = args.get("reason", "Potential fraud detected.")

                    created = record_scam_alert(
                        call_sid=buf.call_sid,
                        senior_id=buf.senior_id,
                        guardian_id=buf.guardian_id,
                        contact_number=buf.from_number,
                        scam_type=scam_type,
                        severity=severity,
                        confidence=confidence,
                        trigger=trigger,
                        summary=reason,
                    )
                    if created:
                        buf.alert_fired = True

                elif name == "end_call":
                    reason = args.get("reason", "Autonomous termination of scammer")
                    end_active_call(buf.call_sid, reason)

                elif name == "warn_senior":
                    message = args.get(
                        "message",
                        "Warning: This caller may be attempting fraud. Please hang up.",
                    )
                    play_warning_to_senior(buf.call_sid, message)

                elif name == "block_number":
                    logger.info(
                        f"[BLOCK_NUMBER_FLAGGED] CallSid={buf.call_sid} Number={buf.from_number}"
                    )
