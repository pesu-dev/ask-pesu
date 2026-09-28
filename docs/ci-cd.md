# CI and deployment

## Continuous integration

| Workflow | Runs on | What it does |
|---|---|---|
| `source.yaml` | Pull requests | Fails a pull request that is not from a fork, comes from a fork's `main`, or targets anything other than `dev` |
| `pre-commit.yaml` | Push, pull request | Every pre-commit hook on every file: ruff lint and format, file hygiene, and Markdown link checks |
| `contract.yaml` | Push, pull request | Checks that each shared file is tracked once; recompiles `requirements.txt` and fails if it differs; runs [`scripts/check_duplication.py`](../scripts/check_duplication.py); copies the shared files in as a deploy does and checks each service's split tree has everything a Space needs |
| `frontend.yaml` | Push and pull request that change `services/api/frontend/` | `tsc --noEmit` on both tsconfig projects, then vitest |
| `docker.yaml` | After `pre-commit.yaml` succeeds on `dev`, or run by hand | Builds both images, starts each container and waits for `/health` |
| `deploy-dev-api.yaml` | Push to `dev`, or run by hand | Deploys the api to `askpesu-dev` |
| `deploy-prod.yaml` | Run by hand | Fast-forwards `main` to `dev`, then deploys the api to `askpesu` and the db to `askpesu-db` |

- `frontend.yaml` is path-filtered, so do not make it a required status check. GitHub would wait
  for it on pull requests that do not run it.
- `docker.yaml` is the only workflow that builds a Dockerfile. It is also the slowest.
- `docker.yaml` starts both containers against `ask-pesu-dev`. The db container runs a real
  listener, which writes.

### Repository secrets

| Secret | Used by |
|---|---|
| `HF_TOKEN` | Both deploy workflows, to push to the Spaces, so it needs write scope. `docker.yaml`, to start the api |
| `QDRANT_URL`, `QDRANT_API_KEY` | `docker.yaml`. The key is a read-write key to `ask-pesu-dev`, never to `ask-pesu-prod` |
| `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET` | `docker.yaml`, to start the db |

`deploy-prod.yaml` also reads the `PROD_DEPLOYMENT_ALLOWED_USERS` repository variable, and refuses
to run for anyone not listed in it.

## Deployment

Every deploy runs [`.github/actions/deploy-space`](../.github/actions/deploy-space/action.yml).
It:

1. copies `conf/collection.yaml`, `requirements.txt`, `LICENSE` and `.env.example` into
   `services/<name>/` and commits them on the runner (the commit is never pushed to GitHub);
2. splits `services/<name>/` into its own history with `git subtree split`;
3. refuses to continue if any of the four files is missing from that tree;
4. force-pushes it to the Space's `main`. Hugging Face builds the image from the Dockerfile.

A deploy replaces the Space's history.

| Workflow | Deploys | To |
|---|---|---|
| `deploy-dev-api.yaml`, on every push to `dev` | api | `askpesu-dev` |
| `deploy-prod.yaml`, by hand | api and db | `askpesu`, `askpesu-db` |

Neither deploy is path-filtered. Every push to `dev` deploys the dev api, and every production
deploy deploys both services, whatever changed.

### Releasing

1. **Merge a pull request into `dev`.** `Deploy API to Dev` runs. Check that `askpesu-dev` serves
   `/health`, `/docs`, the frontend and `/assets`, and streams a real answer.
2. **Run `Deploy to Production`** when `dev` is ready. It fast-forwards `main` to `dev`, and stops
   if the two have diverged. It then deploys both services. Check `askpesu` as in step 1, and check
   that `askpesu-db` serves `/health` and that its logs show the listener started.

Production deploys are infrequent and batch several merges. `dev` is normally ahead of `main`.

### The db is deployed only to production

There is one db Space, `askpesu-db`, and only `deploy-prod.yaml` deploys it. The listener opens
its stream with `skip_existing=True`, so every restart loses the comments posted while it is down,
beyond what the [startup catch-up](ingestion.md#catch-up-on-startup) recovers. Deploying it only on
the infrequent production deploys limits those restarts. See
[decision 0010](decisions/0010-db-deploys-only-to-production.md).

As a result:

- **A `services/db` change merged into `dev` runs nowhere** until the next production deploy. Test
  writer changes locally against `ask-pesu-dev` with a read-write key, and run
  `populate_db.py --dry-run` before a real backfill.
- **A writer change first runs in production.** Changes to `services/db/app/` and
  `services/db/scripts/` require codeowner review. The contract checks catch structural problems
  at startup and on every write. A write that matches the contract but is wrong, such as a broken
  thread rendering, is not caught, and only a backfill replaces it. Watch the db Space's logs and
  `/health` after a production deploy.

`deploy-prod.yaml` does not redeploy the dev api. It tracks `dev`, which is normally ahead of
`main`, and a force-push of `main` would roll it back.

### Space configuration

Each Space needs its secrets under **Settings → Variables and secrets**, with the names in
[configuration.md](configuration.md#environment-variables):

| Space | Secrets | `QDRANT_COLLECTION` | `QDRANT_API_KEY` needs |
|---|---|---|---|
| `askpesu` | `HF_TOKEN`, `QDRANT_URL`, `QDRANT_API_KEY` | `ask-pesu-prod` | Read access |
| `askpesu-dev` | `HF_TOKEN`, `QDRANT_URL`, `QDRANT_API_KEY` | `ask-pesu-prod` | Read access |
| `askpesu-db` | `QDRANT_URL`, `QDRANT_API_KEY`, `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET` | `ask-pesu-prod` | Write access, and manage access if the collection does not exist yet |

All three are Docker Spaces with hardware allocated. The SDK comes from each service README's
frontmatter; the hardware does not, and has to be assigned in the Space's settings.

### Adding an environment

The api refuses to start without a collection that matches the contract, and the db, which creates
it, is only deployed to production. Before pointing an api at a new collection, create the
collection: run `services/db` against it once, or create it by hand as in
[creating a collection](collection-contract.md#creating-a-collection).

## Rollback

On GitHub, revert the merge commit on `dev`. `main` only moves when `deploy-prod.yaml` runs.

To put a Space back on a known-good commit without waiting for a deploy, rebuild the tree the
deploy action would have pushed from that commit, and push it:

```bash
git switch --detach <good-sha>
svc=services/api
mkdir -p $svc/conf
cp conf/collection.yaml $svc/conf/
cp requirements.txt LICENSE .env.example $svc/
git add -f $svc/conf/collection.yaml $svc/requirements.txt $svc/LICENSE $svc/.env.example
git commit -m "Vendor root-level files for deployment"
git subtree split --prefix=$svc HEAD -b rollback
git push https://pesu-dev:$HF_TOKEN@huggingface.co/spaces/pesu-dev/askpesu rollback:main --force
```

`HF_TOKEN` needs write access to the Space. Rolling back `askpesu-db` restarts the listener, with
the same loss of comments as a deploy.
