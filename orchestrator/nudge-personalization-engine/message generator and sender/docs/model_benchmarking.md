# Model Benchmarking: Gemma-3-27B-it and Gemini-3.1-Flash-Lite

This document compares the performance characteristics of our primary (Gemini) and fallback (Gemma) models used in the message generation pipeline.

## Why This Matters

When Gemini hits rate limits (429 errors), the system automatically falls back to Gemma. Understanding the performance gap helps explain quality degradation during high-traffic periods.

---

## General Capability Benchmarks

| Metric                   | Gemma-3-27B-it       | Gemini-3.1-Flash-Lite           |
| ------------------------ | -------------------- | ------------------------------- |
| MMLU (General Knowledge) | 78.6%                | ~88.2%                          |
| HumanEval (Coding)       | 48.8%                | 74.5%                           |
| Context Window           | 128k                 | 1,000k (1M)                     |
| Architecture             | Dense (Open Weights) | Proprietary (API)               |
| Multimodality            | Native (Text/Image)  | Native (Text/Image/Audio/Video) |

---

## Detailed Benchmark Comparison

| Benchmark            | Gemma-3-27B-it | Gemini-3.1-Flash-Lite |
| -------------------- | -------------- | --------------------- |
| MMLU (Knowledge)     | 78.6%          | 88.2%                 |
| GPQA (PhD-level)    | 42.6%          | 46.5%                 |
| HumanEval (Code)     | 87.8%          | 74.5%                 |
| MATH (Hard Logic)    | 89.0%          | 81.2%                 |
| IFEval (Instruction) | 90.4%          | 89.8%                 |

---

## Agent-Specific Benchmarks

Critical for our multi-agent pipeline performance:

| Benchmark                     | Gemma-3-27B-it | Gemini-3.1-Flash-Lite |
| ----------------------------- | -------------- | --------------------- |
| OrchestrationBench (Plan Acc) | 76.5%          | 89.1%                 |
| Intent Routing Accuracy       | 88.0%          | 94.0%                 |
| Multi-step Reasoning (GPQA)   | 42.6%          | 46.5%                 |

---

## Output Quality Benchmarks

| Benchmark                    | Gemma-3-27B-it | Gemini-3.1-Flash-Lite |
| ---------------------------- | -------------- | --------------------- |
| Structured Output Compliance | 92.1%          | 97.0%                 |
| Tool Parameter Accuracy      | 85.8%          | 90.2%                 |
| Terminal-Bench (DevOps)      | 61.2%          | 68.5%                 |

---

## Impact on Message Generation

### Gemini-3.1-Flash-Lite (Primary)
- **Better at:** Complex multi-agent orchestration, following detailed personality constraints, hallucination resistance
- **Context:** 1M tokens — can handle long conversation history
- **JSON compliance:** 97% — reliable structured output for our pipeline

### Gemma-3-27B-it (Fallback)
- **Struggles with:** Multi-step reasoning, complex instruction following, constrained generation
- **Context:** 128k — may truncate long inputs
- **JSON compliance:** 92% — higher failure rate for structured outputs
- **Hallucination:** More likely to invent details not in research signals

## When Fallback Activates

```python
# In llm_service.py, fallback triggers on:
- HTTP 429 (Rate limit exceeded)
- "quota" errors
- "resource_exhausted" errors
- Any primary model exception after 4 retries
```

## Detection in Logs

Look for these patterns in logs to identify fallback events:

```
Both models failed. Primary (gemini-3.1-flash-lite-preview): [...] | Fallback (models/gemma-3-27b-it): [...]
```

Or search for:
```bash
grep -i "429\|quota\|Both models failed\|Fallback\|gemma\|resource_exhausted" app.log
```

## Recommendation

Consider upgrading to a paid Gemini tier (2,000+ RPM) to minimize fallback frequency, or implement request queuing/throttling to stay within free tier limits.
## Sources : 
Google DeepMind / Hugging Face Leaderboards. 

https://llm-stats.com/models/compare/gemma-3-27b-it
https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/gemini/3-1-flash-lite