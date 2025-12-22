# Token Saver Reloaded

A multi-function filter for [OpenWebUI](https://github.com/open-webui/open-webui) that optimizes token usage by trimming history, pruning images, removing filler words, injecting historical timestamps, and using AI/BM25 to retrieve forgotten messages beyond the context window.

## Features

- **Smart Context Lookup (Configless RAG)**: Automatically searches messages that were trimmed from the context window. Uses either `sentence-transformers` for deep semantic matching or `rank-bm25` for lightweight keyword matching, appending relevant past context as `<recovered_memory>`.
- **History trimming**: Keeps only the last `N` messages (default: `50`) to reduce token usage and save LLM costs.
- **Timestamp injection**: Fetches real timestamps from the Open WebUI API and prepends them to historical messages, keeping the model temporally grounded without hallucinations.
- **Image pruning**: Strips image attachments from older messages so text-only models do not waste API bandwidth computing old visual context.
- **Token optimization**: (Disabled by default) Removes filler words and corporate jargon from user messages while safely bypassing code blocks, formatting, and quotes.

## Configuration (Valves)

| Valve | Default | Description |
| :--- | :---: | :--- |
| `priority` | `0` | Execution order (higher equals later execution). |
| `n_last_messages` | `50` | Messages to keep (user and assistant each count as 1). |
| `supplementary_messages_to_be_sent` | `3` | Number of extra relevant past messages to retrieve beyond the cutoff. Set to 0 to disable lookup. |
| `use_bm25_instead_of_sentence_transformer` | `False` | `True` = lightweight BM25 keyword search. `False` = heavy PyTorch semantic search. |
| `debug_mode` | `False` | Emits detailed diagnostics (library status, forgotten messages, evaluation time) to the server log as WARNING. |
| `ignore_images_after_n_messages` | `10` | Retain images only for the last N messages. Older images are stripped. |
| `api_base_url` | `http://127.0.0.1:8080` | Base URL for the Open WebUI API to fetch message timestamps. |
| `inject_system_instructions` | `True` | Append instructions to the System Prompt explaining how to handle the injected time data. |
| `enable_token_optimizer` | `False` | Remove common filler words from user messages to reduce token usage. |
| `min_words_to_optimize` | `60` | Skip optimization for messages shorter than this word count. |
| `max_words_to_optimize` | `2000` | Skip optimization for extremely long messages. |
| `optimize_current_only` | `True` | Only optimize the current (last) message. |

## Requirements

This filter requires the following Python packages to be installed in your Open WebUI environment:

- `httpx>=0.24.0` (usually included in Open WebUI)
- `rank-bm25` (for keyword search)
- `sentence-transformers` (for semantic search)
- `torch` (for semantic search)
