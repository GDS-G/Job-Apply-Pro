# ADR 0012: Provider-independent governed AI Gateway

- Status: Accepted
- Date: 2026-08-05
- Build: AI Gateway `v0.6.0-alpha.1`

## Context

Job Apply Pro needs local and cloud models for different tasks, but provider SDKs in application services would scatter secrets, retry logic, schemas, costs, and privacy decisions across the codebase. Agents also need one stable contract that can be evaluated without a live provider.

## Decision

All AI access occurs through `AIGatewayService`. Provider adapters implement one completion/embedding protocol. OpenAI-compatible primary cloud, secondary compatible cloud, and llama.cpp configurations use the same narrow HTTP adapter; external endpoints require HTTPS and local endpoints require loopback.

The model registry declares provider ownership, capabilities, context limits, costs, and enabled state. Per-task routing policies declare ordered models, required capabilities, external permission, maximum cost, timeout, retries, cache TTL, and fallback. Application services and agents never call provider clients directly.

## Consequences

- Providers and models can change without changing agent or application contracts.
- Local fixtures can validate routing, fallback, schemas, budgets, and agents without network access.
- Provider-specific features must be represented through the shared capability/contract boundary before use.
- An empty provider configuration safely disables model execution while retaining status/readiness APIs.
