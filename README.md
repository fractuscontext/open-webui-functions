# ⏻ Open WebUI Inlet Functions  
  
Claire's best Open WebUI Functions  
  
## Functions

<!-- markdownlint-disable MD033 -->
| Function | Features |  
| -- | -- |
| [token-saver-reloaded][tsr-doc] | - Only sends the last N messages to the provider to save LLM costs and time <br><br> - Injects real timestamps to current and historical messages so the AI knows exactly what time it is <br><br> - Did it trim too much? Re-discover forgotten messages via Semantic (PyTorch) or BM25 search <br><br> - Strips image attachments from older messages to save multimodal token bandwidth <br><br> - Regex that removes filler words and corporate jargon from user prompts without breaking code blocks<br> |  
| [concise-output][co-doc] | - Injects system-level instructions that push the LLM toward concise, structured output <br><br> - Sets a soft target word count and enforces clean bullet points <br><br> - Suppresses preambles (e.g., "As an AI") and filler phrases |
<!-- markdownlint-enable MD033 -->

## Installation

**Requirements**: Open WebUI v0.8.4 or higher.

1. Navigate to **Admin Panel** → **Functions** → **Import From Link**.  
  
2. Paste the preferred raw URL:  
  
   - **Token Saver**: [`token-saver-reloaded.py`][tsr-raw]
   - **Concise Output**: [`concise-output.py`][co-raw]
  
3. Enable the filter.  

## License

MIT License © 2026 fractuscontext

<!-- URL Definitions -->

[tsr-doc]: token-saver-reloaded/token-saver-reloaded.md
[co-doc]: concise-output/concise-output.md
[tsr-raw]: https://raw.githubusercontent.com/fractuscontext/open-webui-functions/main/token-saver-reloaded/token-saver-reloaded.py
[co-raw]: https://raw.githubusercontent.com/fractuscontext/open-webui-functions/main/concise-output/concise-output.py
