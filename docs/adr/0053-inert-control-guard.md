# ADR 0053: Inert control guard

## Status

Accepted for Inert Control Guard `v0.44.0-alpha.1`.

## Context

HTML `inert` removes an element and its descendants from normal interaction and focus behavior without making those descendants match `:disabled`. An inert form control can remain visually laid out and pass CSS visibility checks, so the existing visibility and disabled guards do not prove actionability.

## Decision

The browser worker records a combined `inert` signal plus `direct_inert` and `inherited_inert` provenance. It uses the nearest `[inert]` ancestor, including the element itself, and does not record the ancestor identity or markup.

The desktop excludes inert controls from detected binding choices. Required-field coverage classifies them as manual before native-valid completion, and approved execution independently rejects a freshly observed inert control before sending an action.

## Consequences

- Visually present but interaction-suppressed controls cannot enter approved execution.
- Existing observations remain readable; all inert fields default false.
- Only three booleans are added to bounded observations and shared contracts.
- Dynamic portals must be recaptured after removing inert state.

## Alternatives rejected

- Treating inert as hidden would remove useful operator review context.
- Treating inert as disabled would lose distinct browser provenance and blur different recovery behavior.
- Inferring inert from opacity, pointer-event styles, or animation is unreliable and provider-specific.
