# ADR-0037: Typed application-answer validation

- Status: Accepted
- Date: 2026-08-12
- Build: Typed Application Answers `v0.28.0-alpha.1`

## Context

Application answers were persisted as strings even when a portal expected a boolean, bounded number, ISO date, or enumerated choice. Character limits alone could not prevent a plausible-looking draft from violating the portal field's actual contract. The product source of truth requires exact, short/long text, numeric, date, yes/no, multiple-choice, salary, availability, technology-experience, behavioral, and employer-specific answers.

## Decision

Each application answer records an `ApplicationAnswerKind` and a versioned validation-rules object. Multiple-choice rules contain bounded unique choices. Number and salary rules may carry finite minimum/maximum values. Date and availability rules may carry valid ISO calendar bounds. Other answer kinds reject unrelated constraints.

The same deterministic validator handles library reuse, governed-AI output, and operator review. Yes/no values normalize to `Yes` or `No`; numeric/salary values normalize to a finite decimal without display punctuation; date/availability values normalize to `YYYY-MM-DD`; choices require exact membership; exact and short-text kinds enforce their own bounded shapes in addition to the portal character limit. Invalid reused content is ignored, invalid model content fails safely, and invalid reviewed content returns conflict.

Migration `20260812_0020` adds `answer_kind`, `validation_rules_json`, and a kind index to `application_answers`. Existing records become `SHORT_TEXT` with empty rules. Promotion records type/rules in answer-library provenance so future policy can explain the reviewed source contract without changing locked candidate claims.

## Consequences

- The answer type and its constraints survive restart and remain visible in provenance.
- Ordinary code validates structured values; AI does not decide whether a number, date, boolean, or choice is valid.
- Portal binding still must compare the observed control contract with this typed answer before any fill action.
- Text kinds remain strings and continue through the existing review/promotion boundary.
