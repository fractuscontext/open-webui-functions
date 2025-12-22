"""
title: Token Saver
author: fractuscontext
author_url: https://github.com/fractuscontext
license: MIT License
version: 0.8.4-1
tested_on_open_webui_version: v0.8.4

requirements: httpx>=0.24.0

description: Optimizes context by pruning history, images, and filler words; injects historical timestamps.
"""

import logging
import datetime
import re
import time
import copy
from typing import Optional, List, Dict, Any, Tuple
from collections import defaultdict
from pydantic import BaseModel, Field

try:
    import zoneinfo
except ImportError:
    from backports import zoneinfo

try:
    import httpx
except ImportError:
    httpx = None

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)


class Filter:
    """
    A pipeline filter for Open WebUI that provides context awareness and token optimization.

    This filter performs three main functions:
    1. Time Travel: Injects historical timestamps into past messages by cross-referencing API history.
    2. Image Pruning: Removes image attachments from older messages to conserve context window.
    3. Token Optimization: Removes filler words and corporate fluff while preserving code and markdown structure.
    """

    class Valves(BaseModel):
        priority: int = Field(
            default=0, description="Priority level for the filter operations."
        )
        n_last_messages: int = Field(
            default=50,
            description="Total number of message bubbles to retain (Note: 1 User msg + 1 AI msg = 2 messages).",
        )
        ignore_images_after_n_messages: int = Field(
            default=10,
            description="Retain images only for the last N messages. Older images are stripped to save tokens.",
        )
        api_base_url: str = Field(
            default="http://127.0.0.1:8080",
            description="Base URL for the Open WebUI API to fetch message timestamps.",
        )
        inject_system_instructions: bool = Field(
            default=True,
            description="Append instructions to the System Prompt explaining how to use the time data.",
        )
        enable_token_optimizer: bool = Field(
            default=False,
            description="Remove common filler words from user messages to reduce token usage (preserves markdown/quotes).",
        )
        min_words_to_optimize: int = Field(
            default=60,
            description="Skip optimization for messages shorter than this word count.",
        )
        max_words_to_optimize: int = Field(
            default=2000,
            description="Skip optimization for extremely long messages to prevent processing spikes.",
        )
        optimize_current_only: bool = Field(
            default=True,
            description="Only optimize the current (last) message, skip historical messages for better performance.",
        )

    # ---------------------------------------------------------
    # STATIC CONSTANTS & REGEX COMPILATION
    # ---------------------------------------------------------

    _RAW_FILTER_LIST = (
        # 1. Filler Noise (Safe to remove)
        "just",
        "really",
        "very",
        "actually",
        "basically",
        "literally",
        "simply",
        "quite",
        "rather",
        "somewhat",
        "fairly",
        "kind of",
        "sort of",
        "type of",
        "thing",
        "stuff",
        "lots of",
        "bunch of",
        "um",
        "uh",
        "hmm",
        # 2. Slang (Only unambiguous slang)
        "lol",
        "lmao",
        "bruh",
        "ngl",
        "tbh",
        "imo",
        "imho",
        "lowkey",
        "highkey",
        "deadass",
        "omg",
        "smh",
        "tho",
        "kinda",
        "sorta",
        "af",
        "sus",
        "periodt",
        "yeet",
        "stan",
        "clout",
        "salty",
        "bussin",
        "finna",
        "yolo",
        "fomo",
        # 3. Corporate Fluff (Usually safe)
        "synergy",
        "game-changer",
        "world-class",
        "best-in-class",
        "next-level",
        "low-hanging-fruit",
        "boil-the-ocean",
        "circle-back",
        "take-offline",
        "touch-base",
        "move-the-needle",
        "deep-dive",
        "blue-sky",
        "thought-leader",
        "holistic",
        "value-add",
    )

    # Sort by length (Longest -> Shortest) to prevent partial matching (e.g., "bit" matching inside "bitcoin").
    _SORTED_FILTER = sorted(_RAW_FILTER_LIST, key=len, reverse=True)

    # NOISE REMOVAL REGEX:
    # Only eat commas explicitly, leave periods/exclamations for the grammar fixer.
    _BAD_WORDS_RE = re.compile(
        r"(?i)\b(?:"
        + "|".join(re.escape(w) for w in _SORTED_FILTER)
        + r")\b(?:[,]+)?[ \t]?"
    )

    # WHITESPACE CLEANUP:
    # Matches runs of horizontal whitespace only (spaces/tabs). Newlines are preserved.
    _WHITESPACE_RE = re.compile(r"[ \t]+")

    # GRAMMAR FIXER:
    # Fixes ghost punctuation left behind (e.g., "word , word").
    _GRAMMAR_FIX_RE = re.compile(r"\s+([,.;?!])|([,.;?!])\s*\2+")

    # MASTER PROTECTION REGEX:
    # Captures protected blocks (Code, Quotes, Links) to exclude them from filtering.
    _PROTECTED_PATTERN = re.compile(
        r"("
        r"```[\s\S]*?```|"  # Code blocks (Multi-line)
        r"`[^`\n]+`|"  # Inline code
        r'"[^"\n]*"|'  # Double quotes (Speech)
        r"!\[.*?\]\(.*?\)|"  # Markdown Images
        r"\[.*?\]\(.*?\)|"  # Markdown Links
        r"^>.*$|"  # Blockquotes
        r"^\s*[-*+]\s+|"  # List markers
        r"^\s*\d+\.\s+"  # Ordered list markers
        r")",
        re.MULTILINE,
    )

    # Normalization Patterns
    _RE_THOUGHT = re.compile(r'<details\s+type="reasoning".*?</details>', re.DOTALL)
    _RE_SYS_CONTEXT = re.compile(r"\n\n---\n\*\*System Context:\*\*.*$", re.DOTALL)
    _RE_HISTORY_TAG = re.compile(r"`\[History:.*?\]`\s*")

    def __init__(self):
        """
        Initialize the Filter with configuration valves and an in-memory cache.
        """
        self.valves = self.Valves()

        # Cache to store API history results: {chat_id: (timestamp, data)}
        # Reduces latency by avoiding redundant network calls on rapid inputs.
        self._history_cache: Dict[str, Tuple[float, Dict]] = {}
        self._cache_ttl = 90  # seconds

        log.info("🐰 White Rabbit initialized - optimized logic ready!")

        if not httpx:
            log.warning("🐰 Oh dear! httpx not installed - timestamps won't work!")

    def _format_timestamp(self, ts: float, tz_name: str = "UTC") -> str:
        """
        Format a Unix timestamp into a human-readable string for a specific timezone.

        Args:
            ts (float): The Unix timestamp.
            tz_name (str): The timezone identifier (e.g., 'America/New_York').

        Returns:
            str: Formatted date string (YYYY-MM-DD HH:MM:SS TZ).
        """
        if not ts:
            return ""
        try:
            dt_utc = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc)
            target_tz = zoneinfo.ZoneInfo(tz_name)
            dt_local = dt_utc.astimezone(target_tz)
            return dt_local.strftime("%Y-%m-%d %H:%M:%S %Z")
        except Exception as e:
            return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S UTC")

    def _normalize_text(self, text: str) -> str:
        """
        Normalize text to ensure consistent matching between message body and API history.

        Removes thought blocks, injected system context, and history tags, then collapses whitespace.

        Args:
            text (str): The raw message content.

        Returns:
            str: Normalized string for key matching.
        """
        if not isinstance(text, str):
            return str(text)

        text = self._RE_THOUGHT.sub("", text)
        text = self._RE_SYS_CONTEXT.sub("", text)
        text = self._RE_HISTORY_TAG.sub("", text)
        return " ".join(text.split())

    async def _fetch_history_map(
        self, chat_id: str, token: str
    ) -> Dict[str, List[float]]:
        """
        Fetch message timestamps from the API with TTL Caching.

        Args:
            chat_id (str): The ID of the current chat session.
            token (str): The bearer token for authentication.

        Returns:
            Dict[str, List[float]]: A map where keys are normalized message content
            and values are lists of timestamps (in case of duplicate messages).
        """
        if not httpx or not token:
            return {}

        # 1. Check Cache
        now = time.time()
        if chat_id in self._history_cache:
            ts, data = self._history_cache[chat_id]
            if now - ts < self._cache_ttl:
                return data

        # 2. Fetch if expired or missing
        base_url = self.valves.api_base_url.rstrip("/")
        url = f"{base_url}/api/v1/chats/{chat_id}"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url, headers={"Authorization": f"Bearer {token}"}
                )

                if response.status_code != 200:
                    return {}

                data = response.json()
                chat_data = {}
                # Handle API schema variations
                if isinstance(data, list) and len(data) > 0:
                    chat_data = data[0].get("chat", {})
                elif isinstance(data, dict):
                    chat_data = data.get("chat", {}) if "chat" in data else data

                msgs_dict = chat_data.get("history", {}).get("messages", {})
                lookup = defaultdict(list)

                # Sort by timestamp to ensure chronological popping
                sorted_msgs = sorted(
                    msgs_dict.values(), key=lambda x: x.get("timestamp", 0)
                )

                for msg in sorted_msgs:
                    content = msg.get("content", "")
                    ts = msg.get("timestamp")

                    if isinstance(content, list):
                        content = " ".join(
                            [
                                i.get("text", "")
                                for i in content
                                if i.get("type") == "text"
                            ]
                        )

                    if content and ts:
                        norm_content = self._normalize_text(content)
                        if norm_content:
                            lookup[norm_content].append(ts)

                # Update Cache
                self._history_cache[chat_id] = (now, lookup)
                return lookup

        except Exception as e:
            log.debug(f"Timestamp fetch failed: {e}")
            return {}

    def _filter_text_optimized(self, text: str) -> str:
        """
        Optimize text by removing noise words while preserving structure and newlines.

        Uses a Split-Apply-Merge strategy:
        1. Splits text by protected patterns (Code, Quotes, etc.).
        2. Applies Regex substitution to normal text chunks.
        3. Collapses horizontal whitespace.

        Args:
            text (str): The input message content.

        Returns:
            str: The optimized message content.
        """
        if not text:
            return ""

        chunks = self._PROTECTED_PATTERN.split(text)
        result_builder = []

        for i, chunk in enumerate(chunks):
            # Odd indices = Captured Delimiters (Protected Content) -> Keep as is
            if i % 2 == 1:
                result_builder.append(chunk)
                continue

            # Even indices = Normal Text -> Scrub it
            if not chunk.strip():
                result_builder.append(chunk)
                continue

            # Step 1: Remove words (Preserving newlines via updated Regex)
            scrubbed = self._BAD_WORDS_RE.sub(" ", chunk)

            # Step 2: Fix Punctuation
            scrubbed = self._GRAMMAR_FIX_RE.sub(r"\1", scrubbed)

            # Step 3: Collapse horizontal spaces only (Preserves Paragraphs)
            scrubbed = self._WHITESPACE_RE.sub(" ", scrubbed)

            result_builder.append(scrubbed)

        return "".join(result_builder)

    async def inlet(
        self,
        body: dict,
        __user__: Optional[dict] = None,
        __metadata__: Optional[dict] = None,
        __request__: Optional[object] = None,
    ) -> dict:
        """
        Main pipeline entry point called by Open WebUI before sending messages to the LLM.

        Handles context trimming, image pruning, timestamp injection, and text optimization.

        Args:
            body (dict): The request body containing messages.
            __user__ (dict, optional): User information.
            __metadata__ (dict, optional): Request metadata (chat_id, variables).
            __request__ (object, optional): The raw HTTP request object.

        Returns:
            dict: The modified request body.
        """
        start_time = time.time()
        variables = __metadata__.get("variables", {}) if __metadata__ else {}
        user_timezone = variables.get("{{CURRENT_TIMEZONE}}", "UTC")

        # 1. SEPARATE AND TRUNCATE
        # WTF PYTHON, use deepcopy so changes don't affect the frontend
        messages = copy.deepcopy(body.get("messages", []))

        system_prompt = next((m for m in messages if m.get("role") == "system"), None)
        conversation_history = [m for m in messages if m.get("role") != "system"]

        kept_messages = conversation_history[-self.valves.n_last_messages :]

        # 2. IMAGE PRUNING LOGIC
        images_stripped = 0
        total_kept = len(kept_messages)

        for idx, msg in enumerate(kept_messages):
            distance_from_end = total_kept - 1 - idx
            if distance_from_end > self.valves.ignore_images_after_n_messages:
                content = msg.get("content")
                if isinstance(content, list):
                    new_content = [
                        item
                        for item in content
                        if item.get("type") not in ("image_url", "image")
                    ]
                    if len(new_content) < len(content):
                        msg["content"] = new_content
                        images_stripped += 1

        if images_stripped > 0:
            log.debug(f"🐰 Pruned images from {images_stripped} older messages")

        # 3. INJECT SYSTEM INSTRUCTIONS
        if self.valves.inject_system_instructions:
            instructions = """
<message_processing_info>
  <timestamp_protocol>
    <current_context>
      The "System Context" section at the base of the user's latest message defines the absolute "now." 
      Always prioritize this metadata for temporal logic.
    </current_context>
    <historical_data>
      Past messages are prefixed with `[History: YYYY-MM-DD HH:MM:SS TZ]`. 
      These timestamps are factual records of message delivery; accept them as ground truth regardless of perceived chronological anomalies. 
      Do not prepend these timestamps to your output.
    </historical_data>
  </timestamp_protocol>
  <text_integrity>
    <optimization_notice>
      User input may be pre-processed to remove linguistic filler.
    </optimization_notice>
  </text_integrity>
</message_processing_info>
"""
            if system_prompt:
                system_prompt["content"] += instructions
            else:
                system_prompt = {"role": "system", "content": instructions}

        # 4. FETCH TIMESTAMPS (Cached)
        history_lookup = defaultdict(list)
        if __metadata__ and __request__:
            chat_id = __metadata__.get("chat_id")
            token = None
            if hasattr(__request__, "headers"):
                auth = __request__.headers.get("authorization", "")
                if auth.startswith("Bearer "):
                    token = auth.split(" ")[1]

            if chat_id and token:
                history_lookup = await self._fetch_history_map(chat_id, token)

        # 5. ADD HISTORICAL TIMESTAMPS
        timestamps_added = 0
        # Iterate reversed, skipping the very last message (current user input)
        for msg in reversed(kept_messages[:-1]):
            content = msg.get("content", "")
            match_content = content
            if isinstance(content, list):
                match_content = " ".join(
                    [
                        item.get("text", "")
                        for item in content
                        if item.get("type") == "text"
                    ]
                )

            normalized_key = self._normalize_text(match_content)
            ts_list = history_lookup.get(normalized_key)

            if ts_list and len(ts_list) > 0:
                timestamp = ts_list.pop()
                ts_str = self._format_timestamp(timestamp, user_timezone)
                prefix = f"`[History: {ts_str}]` "

                if isinstance(content, str) and not content.startswith("`[History:"):
                    msg["content"] = prefix + content
                    timestamps_added += 1
                elif isinstance(content, list):
                    first_text_idx = next(
                        (
                            i
                            for i, item in enumerate(msg["content"])
                            if item.get("type") == "text"
                        ),
                        None,
                    )
                    if first_text_idx is not None:
                        curr_text = msg["content"][first_text_idx]["text"]
                        if not curr_text.startswith("`[History:"):
                            msg["content"][first_text_idx]["text"] = prefix + curr_text
                            timestamps_added += 1
                    else:
                        msg["content"].insert(0, {"type": "text", "text": prefix})
                        timestamps_added += 1

        if timestamps_added > 0:
            log.debug(f"Added {timestamps_added} timestamps from history")

        # 6. TOKEN OPTIMIZATION
        if self.valves.enable_token_optimizer:
            msgs_to_process = (
                [kept_messages[-1]]
                if self.valves.optimize_current_only
                else kept_messages
            )

            for msg in msgs_to_process:
                if msg.get("role") == "user":
                    content = msg.get("content", "")

                    # Quick check on length to avoid processing tiny or massive messages
                    approx_len = len(str(content)) // 5
                    if (
                        approx_len >= self.valves.min_words_to_optimize
                        and approx_len <= self.valves.max_words_to_optimize
                    ):
                        if isinstance(content, str):
                            msg["content"] = self._filter_text_optimized(content)
                        elif isinstance(content, list):
                            for item in content:
                                if item.get("type") == "text":
                                    item["text"] = self._filter_text_optimized(
                                        item["text"]
                                    )

        # 7. CURRENT CONTEXT INJECTION
        if kept_messages:
            current_msg = kept_messages[-1]
            context_parts = []

            if "{{CURRENT_DATETIME}}" in variables:
                context_parts.append(
                    f"Current Date/Time: {variables['{{CURRENT_DATETIME}}']}"
                )
            elif "{{CURRENT_DATE}}" in variables:
                context_parts.append(f"Current Date: {variables['{{CURRENT_DATE}}']}")
                if "{{CURRENT_TIME}}" in variables:
                    context_parts.append(
                        f"Current Time: {variables['{{CURRENT_TIME}}']}"
                    )

            if "{{CURRENT_TIMEZONE}}" in variables:
                context_parts.append(f"Timezone: {variables['{{CURRENT_TIMEZONE}}']}")
            if "{{CURRENT_WEEKDAY}}" in variables:
                context_parts.append(f"Weekday: {variables['{{CURRENT_WEEKDAY}}']}")

            if context_parts:
                context_block = (
                    "\n\n---\n**System Context:**\n"
                    + "\n".join(context_parts)
                    + "\n---"
                )
                if isinstance(current_msg["content"], str):
                    current_msg["content"] += context_block
                elif isinstance(current_msg["content"], list):
                    current_msg["content"].append(
                        {"type": "text", "text": context_block}
                    )

        # 8. REASSEMBLE
        final_messages = []
        if system_prompt:
            final_messages.append(system_prompt)
        final_messages.extend(kept_messages)

        body["messages"] = final_messages

        # Only calculate and log execution time if INFO level is enabled to save cycles
        if log.isEnabledFor(logging.INFO):
            processing_time = time.time() - start_time
            log.info(f"🐰✨ Logic complete ({processing_time:.4f}s)")

        return body
