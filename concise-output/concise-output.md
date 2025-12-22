# Concise Output

A system-prompt injection filter for [Open WebUI](https://github.com/open-webui/open-webui) that aggressively shapes LLM responses to be concise, highly structured, and free of conversational filler.

## Features

- **Anti-Preamble & Anti-Filler**: Actively suppresses useless conversational padding (e.g., "As an AI", "Certainly!", "Here is your requested information"). The model gets straight to the point.
- **Format Enforcement**: Pushes the model to prioritize bold-caps headers, bulleted lists, and structured data over walls of dense prose.
- **Word Count Constraints**: Sets a soft baseline length constraint to prevent unprompted rambling, while remaining flexible enough to allow overflow when technical accuracy requires it.

## Configuration (Valves)

| Valve | Default | Description |
| --- | --- | --- |
| `priority` | `0` | Execution order (higher equals later execution). |
| `target_word_count` | `240` | Soft word-count target; the model is instructed to aim for this length but may exceed it for accuracy. |

## Requirements

No extra dependencies are required. This filter uses standard Open WebUI hooks and works completely out of the box.

## Usage Notes

This filter works best when you want your LLM to act as a direct analytical processing engine rather than a conversational chatbot. It pairs perfectly with `token-saver-reloaded` for an optimized, low-latency, and high-signal text environment.
