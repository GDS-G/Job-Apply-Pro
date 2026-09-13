# ADR-0067: Gemini processing budget

## Status and purpose

Accepted for Gemini Processing Budget `v0.57.0-alpha.1`, subject to final integrated and packaged validation. ADR-0061 retains durable cleanup ownership and ADR-0062 normalizes approved image bytes. This decision adds bounded processing-state observation and a shared invocation-local work budget; it does not enable unconfigured providers, alter consent or permit unresolved retention to trigger another upload.

## Invocation-local state and limits

`_GeminiWorkBudget` in `ai/providers.py` contains `deadline: float` and `processing_gets: int = 0`. `GeminiProvider.complete()` creates one instance using the injected monotonic clock plus the existing request timeout. The same deadline follows every image upload start, upload finalization, processing wait/GET, interaction request and response construction in that call. A later image or phase does not receive a new work allowance. The provider object does not hold a mutable global invocation budget.

`_remaining_work(deadline)` returns strictly positive remaining seconds or raises a static `AIProviderError`. Client construction and the individual HTTP request each receive the then-current remainder. `_read_response_body()` checks the deadline before reading, between unchunked decoded body yields and after completion, while enforcing the existing 5 MiB body limit. The provider checks again after interaction/lease processing and after constructing the validated `AIProviderResponse`, so delayed validation cannot return an already-expired successful result.

`_PROCESSING_POLL_SECONDS = 2.0`, `_MAX_PROCESSING_GETS = 30`, `_CLEANUP_BUDGET_SECONDS = 30.0` and `_DELETE_TIMEOUT_SECONDS = 15.0` are product policy constants, not provider service guarantees. The processing count is shared across all files in one invocation. Injectable clock/sleeper functions support deterministic tests; production uses `time.monotonic` and `time.sleep`. No new public setting, schema migration or renderer-controlled endpoint is introduced.

## Durable registration before processing metadata

`_upload_media()` preserves the validated-byte and 5 MiB input boundary. It renews journal ownership, checks remaining work and commits an intent before upload work. Immediately before sending media bytes, it renews ownership and checks remaining time before setting `transfer_started = True`.

An expired upload-start phase that proves no media transfer began can abandon its intent. Once finalization may have occurred, a transport, malformed response or deadline failure without a validated resource name remains an unknown outcome requiring manual review. A timeout is never proof that the provider did not create a file.

Once finalization yields a syntactically valid original resource name, `journal.register(record_id, name)` persists it before checking state, MIME or URI. Failed processing or malformed secondary metadata therefore still reaches deletion of that original known resource. No response may substitute another cleanup target.

## Processing-state observation

`_await_active_media()` repeatedly checks remaining work and calls `_validated_media_uri()`. The latter requires exact original resource name and requested MIME. `ACTIVE` also requires a trusted URI matching the fixed Gemini host and original resource. `FAILED`, unspecified/unknown states, missing fields and malformed metadata fail with static input-free messages. `PROCESSING` is not usable for inference and its reported URI is never followed.

For `PROCESSING`, the adapter checks the shared GET count, renews ownership, sleeps for at most the lesser of two seconds and remaining work, renews again and rechecks the deadline before any GET. The count increases immediately before the request. A response becoming `ACTIVE` on the thirtieth permitted GET remains usable if work time remains; a further GET is prohibited.

`_get_media(name, deadline)` constructs `https://generativelanguage.googleapis.com/v1beta/<original-name>` from the validated fixed runtime base and registered name. It sends a GET with the API-key header, no body and redirects disabled. It expects the bare File object, not an upload-finalization wrapper. The adapter does not list account files, poll response-provided URLs or retry a failed status request inside this loop. Journal ownership is renewed before and after waits and requests, including exceptional request completion.

Google's [Files API](https://ai.google.dev/api/files) defines the processing states and the fixed `files.get` metadata endpoint. The polling interval, aggregate limits and strict trust checks above are application choices.

## Separate cleanup allowance and error precedence

In `complete()`'s `finally`, cleanup receives its own monotonic deadline of 30 seconds. `delete_with_budget(name)` delegates to `_delete_media()` with at most 15 seconds per request and at most the cleanup remainder. `_remaining_delete_timeout()` checks before client construction and again before dispatch; exhausting the cleanup allowance prevents another DELETE but does not skip traversal of the durable journal obligations.

`journal.cleanup()` remains responsible for preserving or relinquishing every obligation even when the network allowance is exhausted. Confirmed deletion follows the existing bounded status policy; asynchronous acceptance is not proof of deletion. DELETE response bodies are not consumed as useful evidence. Original retention errors keep precedence, and an unresolved/uncertain cleanup outcome remains a terminal `AIProviderMediaRetentionError`, preventing gateway retry/fallback from amplifying retention.

An ordinary work or processing failure can remain an ordinary provider error only after known-resource cleanup is confirmed. The existing gateway may then apply its configured retry/fallback policy. Consequently this is one `GeminiProvider.complete()` work budget, not an aggregate deadline across every gateway retry, alternative provider or task. The deletion-only recovery entry point retains its own existing worker policy; it is not a new model invocation or media reupload.

## Deadline and containment limitations

The checks bound admission of subsequent work and observation between synchronous phases. They cannot forcibly cancel an in-flight OS/transport operation at an exact wall-clock instant. [HTTPX timeouts](https://www.python-httpx.org/advanced/timeouts/) cover network phases/inactivity; they are not a guaranteed total-call cancellation mechanism. Client setup, local processing and transport behavior may overrun before control returns. No hard memory/process quota, general gateway deadline or new process-tree containment is claimed.

Normalized image bytes, explicit external-AI/media-upload consent, capability gates, fixed endpoint validation, encrypted cleanup records, same-credential admission, restore preservation and deletion-only recovery continue unchanged. Different API keys do not prove separate provider accounts. Mock deletion evidence does not establish real provider retention, and unknown-resource acknowledgment still requires independent review.

## Validation

Deterministic tests cover ACTIVE without polling; PROCESSING to ACTIVE; failed/unknown states; exact resource/MIME/URI binding; failed GET and trickled-body deadline checks; one budget across phases and multiple images; maximum shared GET count; no-transfer expiry versus uncertain finalization; lease renewal failures; exhausted cleanup that still traverses all obligations; and post-response-construction expiry with correct cleanup/error precedence. Independent review identified the final response-construction deadline gap, which is covered for text, media with confirmed cleanup and media with failed cleanup.

Final exact-version backend/desktop counts, package smoke, artifact hashes and protected integration belong in the production-readiness audit. No live provider call, account credential, uploaded candidate document or provider-retention acceptance is supplied by this synthetic suite.
