# 0010. The db service is deployed only by the production deploy

- **Status:** Accepted

## Context

There is one db Space, `askpesu-db`, and it writes the collection every api reads. The listener
opens its stream with `skip_existing=True`, so comments posted while it is down are not streamed.
The startup catch-up re-indexes only the threads behind the most recent comments. Merges to `dev`
are frequent, and often change files the db image uses, such as `conf/collection.yaml` and
`requirements.txt`.

## Decision

Only `deploy-prod.yaml` deploys the db. Pushes to `dev` deploy only the api, to `askpesu-dev`.

## Consequences

- The listener restarts only on production deploys, which are infrequent.
- A `services/db` change merged to `dev` runs nowhere until the next production deploy, and first
  runs in production. Codeowner review and the contract checks stand in for a staging writer.
  Watch the db Space after each production deploy.
- Writer changes are tested locally against `ask-pesu-dev`.
- Every production deploy restarts the db, whether or not `services/db` changed.

## Alternatives rejected

- **Deploying the db on every push to `dev`.** Restarts the listener often, losing comments each
  time.
