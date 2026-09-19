# Security Policy

## Supported versions

Only what is deployed is supported: the production Spaces, `askpesu` and `askpesu-db`, built from `main`. Fixes land on `dev` and reach production at the next promotion.

## Reporting a vulnerability

Do not open a public issue for a security problem.

Report it privately to the maintainers, either in the `#pesu-dev` channel on the [PESU Discord](https://discord.gg/eZ3uFs2) or by contacting a maintainer directly. Include:

- steps to reproduce it
- what someone could do with it
- a suggested fix, if you have one

We will acknowledge the report within 48 hours and keep you updated.

## What is in scope

- **The public endpoints.** `POST /ask` and `POST /rewriteQuery` are public and unauthenticated, and every accepted request spends inference quota. A way to make one request cost far more than intended — in quota, cross-encoder time or memory — is in scope.
- **Credentials.** The Qdrant, Hugging Face and Reddit credentials are held server-side as Space secrets. Any path by which one reaches a response, a client or a log line is in scope.
- **The Qdrant collection.** Only the db service writes to it. A way to write to it, or to read another collection, through either service is in scope.
- **Operational endpoints.** `/health` and `/quota` report service state and should report nothing else.

## What happens to your questions

Conversations are held in your browser and sent with each request; the server does not store them. The server does log each question it receives.

## Disclaimer

askPESU answers from public discussions on r/PESU. It is not an official PES University service, and its answers are not official information. Each answer lists the threads it was drawn from, with their dates — check them before relying on anything, particularly fees, cutoffs and deadlines, which change.

Use this software at your own risk. We do not take responsibility for third-party applications built on this API.
