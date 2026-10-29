"""Custom exceptions for pipeline errors and clarification requests."""


class PipelineError(Exception):
    """Raised when a pipeline step fails and cannot be recovered."""
    pass


class ClarificationRequired(Exception):
    """Raised when a pipeline step needs human clarification to proceed."""
    pass
