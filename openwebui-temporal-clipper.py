"""
title: openwebui-temporal-clipper / Time-Aware Context Clipper
author: fractuscontext
author_url: https://github.com/fractuscontext
license: MIT License
version: 0.6.40-2
tested_on_open_webui_version: v0.6.40

requirements: httpx>=0.24.0

description: 
- Perplexity-style context management: 
    Retains the conversation to the last `N` messages while injecting accurate timestamps.
    Uses browser-provided time data for the current message and fetches historical timestamps from the API.
"""


import logging
import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

# Standard Python 3.9+ library for IANA timezones
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
    class Valves(BaseModel):
        priority: int = Field(
            default=0, description="Priority level for the filter operations."
        )
        n_last_messages: int = Field(
            default=5, description="Number of last messages to retain."
        )
        enable_api_fallback: bool = Field(
            default=True, description="If timestamps are missing, fetch them from the server API?"
        )
        api_base_url: str = Field(
            default="http://127.0.0.1:8080", 
            description="Base URL for the Open WebUI API."
        )
        inject_system_instructions: bool = Field(
            default=True, 
            description="Append instructions to the System Prompt explaining how to use the time data."
        )

    def __init__(self):
        self.valves = self.Valves()
        log.info("🐰 White Rabbit initialized! Checking my pocket watch...")

    def _format_timestamp(self, ts: float, tz_name: str = "UTC") -> str:
        if not ts: return ""
        try:
            dt_utc = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc)
            target_tz = zoneinfo.ZoneInfo(tz_name)
            dt_local = dt_utc.astimezone(target_tz)
            return dt_local.strftime("%Y-%m-%d %H:%M:%S %Z")
        except Exception as e:
            log.warning(f"🐰 Nearly late! Falling back to UTC... (Timezone parsing failed: {e})")
            return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S UTC")

    async def _fetch_history_map(self, chat_id: str, token: str) -> Dict[str, float]:
        if not httpx:
            log.warning("🐰 Oh dear! Oh dear! httpx not installed, can't fetch history!")
            return {}
        if not token:
            log.warning("🐰 No token for tea time! Can't authenticate with API.")
            return {}
            
        base_url = self.valves.api_base_url.rstrip('/')
        url = f"{base_url}/api/v1/chats/{chat_id}"
        
        log.info(f"🐰 Hopping down the rabbit hole to fetch history from {url}...")
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers={"Authorization": f"Bearer {token}"})
                if response.status_code == 200:
                    data = response.json()
                    msgs = data.get("chat", {}).get("history", {}).get("messages", {})
                    lookup = {}
                    for msg in msgs.values():
                        content = msg.get("content", "")
                        ts = msg.get("timestamp")
                        if isinstance(content, list):
                            content = " ".join([i.get("text", "") for i in content if i.get("type") == "text"])
                        if content and ts:
                            lookup[content] = ts
                    log.info(f"🐰 Found {len(lookup)} timestamps in Wonderland's history!")
                    return lookup
                else:
                    log.warning(f"🐰 The Queen's guards blocked me! Status: {response.status_code}")
        except Exception as e:
            log.warning(f"🐰 Tumbled through the wrong rabbit hole! Error: {e}")
        return {}

    async def inlet(
        self, 
        body: dict, 
        __user__: Optional[dict] = None, 
        __metadata__: Optional[dict] = None, 
        __request__: Optional[object] = None
    ) -> dict:
        
        log.debug("🐰 I'm late! I'm late! Processing messages...")
        
        variables = __metadata__.get("variables", {}) if __metadata__ else {}
        user_timezone = variables.get("{{CURRENT_TIMEZONE}}", "UTC")
        log.info(f"🐰 User's timezone: {user_timezone}")

        # 1. SEPARATE AND TRUNCATE
        messages = body.get("messages", [])
        system_prompt = next((m for m in messages if m.get("role") == "system"), None)
        other_messages = [m for m in messages if m.get("role") != "system"]
        kept_messages = other_messages[-self.valves.n_last_messages :]
        
        if len(other_messages) > self.valves.n_last_messages:
            log.info(f"🐰 Trimming the hedgehogs! Kept {self.valves.n_last_messages} of {len(other_messages)} messages.")

        # 2. INJECT SYSTEM INSTRUCTIONS
        if self.valves.inject_system_instructions:
            instructions = (
                "\n\n## TEMPORAL AWARENESS & CONTEXT\n"
                "You are running with a \"Time-Aware\" filter. Use the metadata provided in the messages as your source of truth:\n"
                "1. **Current Time**: The definitive \"Now\" (Date, Time, Timezone) is appended to the bottom of the user's *latest* message in a `**System Context:**` block.\n"
                "2. **Conversation History**: Previous user messages may have a `[History: YYYY-MM-DD ...]` timestamp prefix. Use these to understand the timeline.\n\n"
                "*Note: The timezone and time are extracted from the user's browser via JavaScript. While generally accurate to the user's settings, it may not immediately reflect physical location if the user is traveling.*"
            )
            
            if system_prompt:
                system_prompt["content"] += instructions
            else:
                system_prompt = {"role": "system", "content": instructions}
            log.debug("🐰 Added temporal awareness instructions to system prompt!")

        # 3. HISTORY TIMESTAMPS
        history_lookup = None
        timestamps_added = 0
        
        for i, msg in enumerate(kept_messages[:-1]): 
            content = msg.get("content", "")
            match_content = content
            if isinstance(content, list):
                match_content = " ".join([item.get("text", "") for item in content if item.get("type") == "text"])

            timestamp = msg.get("timestamp")
            
            # Fetch fallback if needed
            if timestamp is None and self.valves.enable_api_fallback and history_lookup is None:
                if __metadata__ and __request__:
                    chat_id = __metadata__.get("chat_id")
                    headers = getattr(__request__, "headers", {})
                    auth = headers.get("authorization", "")
                    token = auth.split(" ")[1] if auth.startswith("Bearer ") else None
                    if chat_id and token:
                        history_lookup = await self._fetch_history_map(chat_id, token)

            if timestamp is None and history_lookup:
                timestamp = history_lookup.get(match_content)

            if timestamp:
                ts_str = self._format_timestamp(timestamp, user_timezone)
                prefix = f"`[History: {ts_str}]`\n"
                if isinstance(content, str) and not content.startswith("`[History:"):
                    msg["content"] = prefix + content
                    timestamps_added += 1
                elif isinstance(content, list):
                    msg["content"].insert(0, {"type": "text", "text": prefix})
                    timestamps_added += 1
        
        if timestamps_added > 0:
            log.info(f"🐰⏰ Added {timestamps_added} historical timestamps!")
        else:
            log.debug("🐰 No historical timestamps to add (new chat or first message)")

        # 4. CURRENT CONTEXT
        if kept_messages:
            current_msg = kept_messages[-1]
            context_parts = []
            
            if "{{CURRENT_DATETIME}}" in variables:
                context_parts.append(f"Current Date/Time: {variables['{{CURRENT_DATETIME}}']}")
            elif "{{CURRENT_DATE}}" in variables:
                context_parts.append(f"Current Date: {variables['{{CURRENT_DATE}}']}")
                if "{{CURRENT_TIME}}" in variables:
                    context_parts.append(f"Current Time: {variables['{{CURRENT_TIME}}']}")
            
            if "{{CURRENT_TIMEZONE}}" in variables:
                context_parts.append(f"Timezone: {variables['{{CURRENT_TIMEZONE}}']}")
            if "{{CURRENT_WEEKDAY}}" in variables:
                context_parts.append(f"Weekday: {variables['{{CURRENT_WEEKDAY}}']}")

            if context_parts:
                context_block = "\n\n---\n**System Context:**\n" + "\n".join(context_parts) + "\n---"
                if isinstance(current_msg["content"], str):
                    current_msg["content"] += context_block
                elif isinstance(current_msg["content"], list):
                    current_msg["content"].append({"type": "text", "text": context_block})
                log.debug("🐰 Current time context added to latest message!")

        # 5. REASSEMBLE
        final_messages = []
        if system_prompt:
            final_messages.append(system_prompt)
        final_messages.extend(kept_messages)
        
        body["messages"] = final_messages
        log.info("🐰✨ Time travel complete! Off to the tea party!")
        return body