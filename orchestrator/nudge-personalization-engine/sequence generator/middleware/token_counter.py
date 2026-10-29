"""Simple token counting middleware for LLM API calls.

The middleware provides a lightweight way to estimate token usage for a given prompt.
It can be extended to use a proper tokenizer (e.g., tiktoken) but for the purpose of
expense management we approximate tokens by splitting on whitespace.
"""

class TokenCounter:
    def __init__(self):
        self.total_tokens = 0

    def count(self, text: str) -> int:
        """Return an estimated token count for *text*.

        The estimation simply counts whitespace‑separated words, which is a reasonable
        proxy for many LLM providers. The count is added to the running total.
        """
        token_count = len(text.split())
        self.total_tokens += token_count
        return token_count

    def reset(self):
        """Reset the accumulated token count to zero."""
        self.total_tokens = 0
