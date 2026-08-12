# ADR-0036: Answer provenance and review-gated drafting

- Status: Accepted
- Date: 2026-08-12
- Build: Answer Provenance & Drafting `v0.27.0-alpha.1`

## Context

An application form question is not the same thing as a reusable answer. A portal-specific question can have a character limit, job context, retrieved evidence, a model draft, and operator corrections that must remain auditable. The dormant `application_answers` table did not capture the question, revision, model identity, evidence, retrieval result, limit, reuse decision, or review state. Reusing or learning from generated text without those controls could turn an unsupported draft into a durable candidate fact.

## Decision

Every encountered question becomes an encrypted, application-scoped record. Drafting first retrieves approved material for the same profile and reuse scope. An exact canonical-field library match may supply a draft. When the operator explicitly enables AI, the service routes through the governed AI gateway with employment-sensitive classification and supplies only retrieved, locked candidate claims. External routes additionally require explicit consent. A model result must cite a non-empty subset of those claims and remains `NEEDS_REVIEW`.

No draft can promote itself. Saving reviewed text requires the exact `SAVE REVIEWED APPLICATION ANSWER` phrase and the revision the operator reviewed. Promoting that reviewed record requires a separate native confirmation and exact `PROMOTE REVIEWED ANSWER` phrase. Promotion atomically changes the application record, creates revision 1 of a locked approved library answer, and creates its retrieval chunk. Stale revisions and non-reviewed promotion fail closed.

Migration `20260812_0019` expands `application_answers` with encrypted question/normalized text, profile/job ownership, status/source, immutable generated text, evidence and retrieval provenance, provider/model/prompt/policy identifiers, confidence, character-limit handling, limitations, user-edit state, reuse permission, revision, and timestamps. Legacy records are marked `LEGACY_REVIEW_REQUIRED`; profile and job ownership are backfilled from their application without decrypting prior values.

## Consequences

- The desktop exposes unresolved questions, provenance, model identity, evidence, limits, review, and promotion as separate operations.
- Failed or disabled drafting is durable work for the operator instead of an invented answer.
- Model output and operator corrections cannot modify locked profile claims.
- Portal passwords, browser profiles, and live submissions are outside this workflow.
- Typed answer semantics and portal field binding remain separate follow-on work.
