# Model Usage

macAgentic uses LiteLLM's native Responses API model. Every successful model
call contributes to cumulative session usage, including intermediate calls in
tool loops.

Usage tracks the provider-reported total input, cached input, cache writes,
output, and calculated USD cost. Cached input and cache writes are details of
input processing; they are not added to the input total. Missing provider
details count as zero.

In terminal mode, cumulative process usage is printed once after each turn
completes (not after intermediate tool-loop model calls). When stdout is a
terminal, labels and values may be colored; redirected output and `NO_COLOR`
use this exact plain-text form:

```text
Usage  Input: 12,345  Cached: 8,192  Writes: 4,096  Output: 1,024  Cost: $0.65
```

In UI mode, the top-right status shows cumulative usage for the active tab:

```text
gpt-5.6-terra / $0.65
Input: 12,345 / Cached: 8,192
Writes: 4,096 / Output: 1,024
```

Usage is session-only metadata. It is never written to the Markdown transcript.
