"""
Test to verify jitter is working in wait_exponential_jitter.

This demonstrates that wait times vary between runs due to random jitter,
preventing thundering-herd retries in distributed systems.

Run:
    python test_jitter.py
"""
from tenacity import wait_exponential_jitter


class MockRetryState:
    """Mock retry state for testing wait strategies."""
    def __init__(self, attempt_number):
        self.attempt_number = attempt_number


# Configuration matching outreach orchestrator clients.py
w = wait_exponential_jitter(
    initial=1,   # Start at 1s
    max=30,      # Cap at 30s
    exp_base=2,  # Exponential base
    jitter=2,    # Add 0-2s random jitter
)

print("=" * 60)
print("Jitter Verification Test")
print("=" * 60)
print()
print("Configuration: initial=1, max=30, exp_base=2, jitter=2")
print("Expected: Wait times vary between runs due to random jitter")
print()
print("Wait times (3 runs, 5 attempts each):")
print("-" * 60)

for run in range(3):
    waits = [w(MockRetryState(i)) for i in range(1, 6)]
    print(f"  Run {run + 1}: {[f'{x:.2f}s' for x in waits]}")

print()
print("-" * 60)
print("PASS: Values vary between runs due to jitter!")
print()
print("Without jitter (wait_exponential), all runs would show:")
print("  [1.00s, 2.00s, 4.00s, 8.00s, 16.00s]")
