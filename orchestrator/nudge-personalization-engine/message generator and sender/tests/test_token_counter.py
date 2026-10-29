"""Unit tests for the token counter middleware."""

import pytest
from middleware.token_counter import TokenCounter

class TestTokenCounter:
    """Test suite for the TokenCounter class."""

    def test_initialization(self):
        """Test that TokenCounter initializes with zero tokens."""
        counter = TokenCounter()
        assert counter.total_tokens == 0
        assert counter.get_total() == 0

    def test_count_single_word(self):
        """Test counting a single word."""
        counter = TokenCounter()
        result = counter.count("hello")
        assert result == 1
        assert counter.get_total() == 1

    def test_count_multiple_words(self):
        """Test counting multiple words."""
        counter = TokenCounter()
        result = counter.count("hello world this is a test")
        assert result == 6
        assert counter.get_total() == 6

    def test_count_with_punctuation(self):
        """Test that punctuation doesn't affect word counting."""
        counter = TokenCounter()
        result = counter.count("Hello, world! How are you today?")
        assert result == 6  # Hello, world, How, are, you, today

    def test_count_empty_string(self):
        """Test counting an empty string."""
        counter = TokenCounter()
        result = counter.count("")
        assert result == 0
        assert counter.get_total() == 0

    def test_count_none(self):
        """Test counting None input."""
        counter = TokenCounter()
        result = counter.count(None)
        assert result == 0
        assert counter.get_total() == 0

    def test_count_non_string(self):
        """Test counting non-string input."""
        counter = TokenCounter()
        result = counter.count(123)
        assert result == 0
        assert counter.get_total() == 0

    def test_accumulation_across_multiple_counts(self):
        """Test that token counts accumulate correctly."""
        counter = TokenCounter()
        counter.count("first sentence")
        counter.count("second sentence with more words")
        assert counter.get_total() == 7  # 2 + 5

    def test_reset_functionality(self):
        """Test that reset clears the accumulated count."""
        counter = TokenCounter()
        counter.count("some text with words")
        assert counter.get_total() == 4
        counter.reset()
        assert counter.get_total() == 0
        assert counter.total_tokens == 0

    def test_multiple_resets(self):
        """Test multiple reset operations."""
        counter = TokenCounter()
        counter.count("word1 word2")
        counter.reset()
        counter.count("word3 word4 word5")
        assert counter.get_total() == 3

    def test_large_text(self):
        """Test counting a larger text."""
        counter = TokenCounter()
        large_text = " ".join([f"word{i}" for i in range(100)])
        result = counter.count(large_text)
        assert result == 100
        assert counter.get_total() == 100

if __name__ == "__main__":
    pytest.main([__file__, "-v"])