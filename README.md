# ⚡ Time-Aware Context Clipper

Perplexity-style filter function for OpenWebUI that combines context clipping + time injection in one pass. **Faster than running two separate filters.**

**Author:** [@fractuscontext](https://github.com/fractuscontext) • **Tested on** OpenWebUI v0.6.40 • MIT License

## What It Does

1. **Clips conversations** to last N messages (default: 5)
2. **Adds timestamps** to historical messages (converted to your timezone)
3. **Injects current time** from browser into the latest message
4. **Teaches the LLM** how to interpret the time metadata via auto-injected system prompt

## Installation

**Requirements**: `httpx` (pre-installed in Docker; run `pip install httpx` for bare metal).

## Configuration (Valves)

| Setting | Default | Description |
|---------|---------|-------------|
| `n_last_messages` | `5` | How many messages to keep |
| `api_base_url` | `http://127.0.0.1:8080` | Your Open WebUI URL |
| `enable_api_fallback` | `True` | Fetch chat history for timestamps |
| `inject_system_instructions` | `True` | Add temporal awareness instructions |

### Setup Notes

- **Docker users:** Change `api_base_url` to `http://host.docker.internal:8080` or `https://openwebui.yourdomain.org`
- **Timezone:** Extracted from browser JS settings, not GPS location.

## Why It's Fast

| Features | Benefit |
|--------------|---------|
| **Single API call** | Fetches history once, not twice |
| **No BeautifulSoup** | No HTML parsing overhead |
| **Async-first** | Non-blocking I/O with `httpx` |
| **Processes only N messages** | Skips the entire chat history, only touches what matters |

**Result:** One fetch, one loop, minimal processing. Other filters parse XML, iterate full history, or run sequentially.

## What the LLM Sees

**What the System Prompt Looks Like:**
```
You are a helpful assistant blablblablabla. ← Your original system prompt

## TEMPORAL AWARENESS & CONTEXT ← This section is automatically appended by the filter
You are running with a "Time-Aware" filter. Use the metadata as your source of truth:
1. **Current Time**: The definitive "Now" is in the `**System Context:**` block at the end of the latest user message.
2. **Conversation History**: Previous messages have `[History: ...]` timestamp prefixes.

*Note: Time is extracted from the user's browser. It reflects their OS timezone settings, not GPS location.*
```

**User's Message (historical):**
```
[History: 2025-12-15 14:30:45 ACDT]
What's the weather like?
```

**User's Message (current):**
```
Hi :3333333

---
**System Context:**
Current Date/Time: Mon Dec 15 2025, 20:52:17
Timezone: Australia/Adelaide
Weekday: Monday
---
```

**⭐ If this saved you time, star the repo!**

Made with ☕ by [@fractuscontext](https://github.com/fractuscontext)
