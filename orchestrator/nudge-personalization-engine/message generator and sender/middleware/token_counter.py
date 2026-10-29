"""Token counting middleware for LLM API calls in the Message Generator and Sender project.

This middleware provides a lightweight way to estimate token usage for prompts and messages.
It follows the same pattern as the Sequence Generator's token counter for consistency across projects.
"""

class TokenCounter:
    def __init__(self):
        """Initialize a new token counter with zero accumulated tokens."""
        self.total_tokens = 0

    def count(self, text: str) -> int:
        """Return an estimated token count for the given text.

        The estimation counts whitespace-separated words, which provides a reasonable
        proxy for token usage across most LLM providers. The count is added to the
        running total.

        Args:
            text: The input text to count tokens for

        Returns:
            The estimated token count for this text
        """
        if not text or not isinstance(text, str):
            return 0

        token_count = len(text.split())
        self.total_tokens += token_count
        return token_count

    def reset(self):
        """Reset the accumulated token count to zero."""
        self.total_tokens = 0

    def get_total(self) -> int:
        """Return the total accumulated token count.

        Returns:
            The total number of tokens counted so far
        """
        return self.total_tokens