# Failure handling

Both services check their configuration and dependencies at startup and refuse to start on a
problem, so a misconfigured deployment does not answer from the wrong data. Once running, the api
reports failures inside the answer stream, and the db listener reports them on `/health`.

## Quota and cooldowns

Hugging Face Inference refuses requests when the account is rate limited (HTTP 429) or when its
included credits are spent (HTTP 402). Each model, primary and thinking, has its own cooldown in
`services/api/app/quota.py`, so a refusal for one leaves the other usable.

1. **A refusal arrives during streaming**, after the 200 status has been sent. The api sends an
   `error` event and starts a cooldown for the model that refused:
   - after a **429**, for `cooldown_hours` (24);
   - after a **402**, until the time Hugging Face reports the credits renew. If that lookup
     fails, for 24 hours.
2. **While a model is in cooldown**, `/ask` requests for it are refused with a 429 before
   streaming starts. The body carries the quota state of both models, so a client can say when to
   retry and whether the other mode works. `/rewriteQuery` falls back to the first eight words of
   the question instead of calling the primary model.
3. **Cooldowns end on the first read after they expire.** There is no background timer.

`quota_refusal()` in `services/api/app/rag.py` decides whether an error is a refusal. It uses the
HTTP status code when the exception carries one, and otherwise looks for phrases such as "rate
limit" or "credits" in the message. Under `LLM_MODE=ollama` nothing is treated as a refusal and
no cooldown starts.

Cooldown state is held in process memory. A restart clears it, and separate replicas would each
keep their own.

## What happens when

| Situation | What happens |
|---|---|
| `QDRANT_COLLECTION` unset | Both services refuse to start |
| The collection is missing | The db creates it. The api refuses to start |
| The collection's geometry or sparse modifier differs from the contract | Both services refuse to start, naming the value |
| The embedding model is not the contracted one, or produces the wrong width | Both services refuse to start |
| `HF_TOKEN` unset | The api raises `KeyError` before serving (except under `ENV=test`) |
| An invalid setting in `config.yaml` | The api refuses to start, naming the setting; see [configuration.md](configuration.md#checked-at-startup) |
| `LLM_MODE` is neither `hf` nor `ollama`, or a variable `ollama` needs is unset | The api refuses to start, naming the mode or variable |
| `LLM_MODE=ollama`, and the server is unreachable or a model was never pulled | The api refuses to start, naming the URL or the model to pull |
| Reddit credentials missing or rejected | The db refuses to start |
| The frontend was never built | The api logs a warning, serves every API route, and returns 503 from `/` |
| A payload's keys differ from the contract | The db's listener stops and `/health` returns 503 |
| Five writes in a row fail | The db's `/health` returns 503; the listener keeps retrying |
| A Reddit or network error in the listener | Logged, and the stream is re-entered |
| The provider refuses for quota | An `error` event, then a cooldown for that model |
| Any other failure while answering | An `error` event carrying the exception's message, then `done` |
| `/ask` exceeds `limits.timeout_seconds` | An `error` event, then `done` |
| The thinking model spends its budget before finishing its reasoning | The reasoning so far as `step` events, then an `error` event |
| A prompt is longer than `OLLAMA_NUM_CTX` | ollama refuses it; the `error` event gives both sizes |
| Nothing clears the reranker's cutoff | The model says it does not have that information |
