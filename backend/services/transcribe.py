import os
import asyncio
import logging
from typing import Optional, Callable, Any
from dotenv import load_dotenv

from deepgram import AsyncDeepgramClient
from deepgram.core.events import EventType
from deepgram.listen.v1.types import ListenV1Results

from backend.db import insert_call_transcript

load_dotenv()
logger = logging.getLogger("trot.transcribe")

DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "").strip()


class DeepgramLiveSession:
    """
    Manages a live WebSocket transcription session with Deepgram Nova-2.
    Forwards mulaw 8000Hz audio from Twilio and persists final utterances
    to Supabase call_transcripts table once the call is in_progress.
    """

    is_active: bool = False

    def __init__(
        self,
        call_sid: str,
        senior_id: Optional[str] = None,
        guardian_id: Optional[str] = None,
        on_transcript: Optional[Callable[[str, str], Any]] = None,
    ):
        self.call_sid = call_sid
        self.senior_id = senior_id
        self.guardian_id = guardian_id
        self.on_transcript = on_transcript

        self._client: Optional[AsyncDeepgramClient] = None
        self._connect_ctx = None
        self._ws = None
        self._listen_task: Optional[asyncio.Task] = None
        self.is_active = False

    async def start(self) -> None:
        """Establishes WebSocket connection to Deepgram Nova-2."""
        if not DEEPGRAM_API_KEY:
            logger.warning(
                f"[DEEPGRAM_DISABLED] DEEPGRAM_API_KEY not configured. Transcription skipped for {self.call_sid}"
            )
            return

        try:
            self._client = AsyncDeepgramClient(api_key=DEEPGRAM_API_KEY)
            self._connect_ctx = self._client.listen.v1.connect(
                model="nova-2",
                language="en",
                encoding="mulaw",
                sample_rate=8000,
                punctuate=True,
                interim_results=False,
            )
            self._ws = await self._connect_ctx.__aenter__()

            # Register event handlers
            self._ws.on(EventType.MESSAGE, self._on_message)
            self._ws.on(EventType.ERROR, self._on_error)
            self._ws.on(EventType.CLOSE, self._on_close)

            # Start background listener loop
            self._listen_task = asyncio.create_task(self._ws.start_listening())
            self.is_active = True
            logger.info(
                f"[DEEPGRAM_CONNECTED] Nova-2 live stream active for CallSid={self.call_sid}"
            )
        except Exception as e:
            logger.error(
                f"[DEEPGRAM_ERROR] Failed to start live session for {self.call_sid}: {e}",
                exc_info=True,
            )
            self.is_active = False

    async def send_audio(self, raw_bytes: bytes) -> None:
        """Sends raw mulaw 8kHz audio chunk to Deepgram."""
        if self.is_active and self._ws:
            try:
                await self._ws.send_media(raw_bytes)
            except Exception as e:
                logger.warning(
                    f"[DEEPGRAM_SEND_FAILED] CallSid={self.call_sid}: {e}"
                )

    async def _on_message(self, message: Any) -> None:
        """Processes incoming Deepgram transcription messages."""
        try:
            msg_type = getattr(message, "type", None)
            if isinstance(message, dict):
                msg_type = message.get("type")

            if msg_type != "Results":
                return

            is_final = getattr(message, "is_final", False)
            if isinstance(message, dict):
                is_final = message.get("is_final", False)

            if not is_final:
                return

            # Extract confirmed transcript text
            transcript_text = ""
            channel = getattr(message, "channel", None)
            if channel and hasattr(channel, "alternatives"):
                alts = channel.alternatives
                if alts and len(alts) > 0:
                    transcript_text = getattr(alts[0], "transcript", "").strip()
            elif isinstance(message, dict):
                channel_dict = message.get("channel", {})
                alts = channel_dict.get("alternatives", [])
                if alts and len(alts) > 0:
                    transcript_text = alts[0].get("transcript", "").strip()

            if not transcript_text:
                return

            logger.info(
                f"[TRANSCRIPT] CallSid={self.call_sid}: \"{transcript_text}\""
            )

            # In-progress gating: only save transcripts after senior answers
            from backend.main import get_active_call_status

            status = get_active_call_status(self.call_sid)
            if status != "in_progress":
                logger.info(
                    f"[TRANSCRIPT_GATED] CallSid={self.call_sid} (Call status is '{status}', not 'in_progress')"
                )
                return

            # Persist to Supabase call_transcripts table
            if self.senior_id and self.guardian_id:
                try:
                    insert_call_transcript(
                        call_sid=self.call_sid,
                        senior_id=self.senior_id,
                        guardian_id=self.guardian_id,
                        text=transcript_text,
                    )
                except Exception as e:
                    logger.error(
                        f"[DB_ERROR] Failed to insert transcript for {self.call_sid}: {e}"
                    )

            # Forward to external callback (for Phase 2 detection buffer)
            if self.on_transcript:
                if asyncio.iscoroutinefunction(self.on_transcript):
                    await self.on_transcript(self.call_sid, transcript_text)
                else:
                    self.on_transcript(self.call_sid, transcript_text)

        except Exception as e:
            logger.error(
                f"[TRANSCRIPT_PARSE_ERROR] CallSid={self.call_sid}: {e}",
                exc_info=True,
            )

    def _on_error(self, error: Any) -> None:
        logger.error(f"[DEEPGRAM_STREAM_ERROR] CallSid={self.call_sid}: {error}")

    def _on_close(self, close_info: Any) -> None:
        logger.info(f"[DEEPGRAM_STREAM_CLOSED] CallSid={self.call_sid}")
        self.is_active = False

    async def stop(self) -> None:
        """Closes the Deepgram WebSocket stream cleanly."""
        if not self.is_active and not self._ws:
            return

        self.is_active = False
        try:
            if self._ws:
                await self._ws.send_close_stream()
        except Exception:
            pass

        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()

        if self._connect_ctx:
            try:
                await self._connect_ctx.__aexit__(None, None, None)
            except Exception:
                pass

        logger.info(
            f"[DEEPGRAM_DISCONNECTED] Live session closed for CallSid={self.call_sid}"
        )
