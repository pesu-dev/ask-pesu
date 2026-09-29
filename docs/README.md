# Documentation

Start with [Architecture](architecture.md) for how the pieces fit together, then read whichever
document covers the part you are changing.

| If you want to… | Read |
|---|---|
| Understand what the two services are and how the repository is laid out | [architecture.md](architecture.md) |
| Change retrieval, reranking, ranking, prompts or streaming | [pipeline.md](pipeline.md), [configuration.md](configuration.md) |
| Change what gets indexed, or rebuild a collection from a Reddit dump | [ingestion.md](ingestion.md) |
| Change the embedding model, vectors or payload keys | [collection-contract.md](collection-contract.md) |
| Call the API, or change a route or stream event | [api.md](api.md) |
| Set up `.env`, or change a runtime setting | [configuration.md](configuration.md) |
| Work on the web UI | [frontend.md](frontend.md) |
| Know what happens when a model, Qdrant or Reddit fails | [failure-handling.md](failure-handling.md) |
| Install dependencies, run the services, run checks | [development.md](development.md) |
| Understand CI, deploy to the Spaces, or roll back | [ci-cd.md](ci-cd.md) |
| Know why something is the way it is before proposing to change it | [decisions/](decisions/README.md) |

## Terms

These three words are used with exact meanings throughout:

- A **post** (or submission) is a Reddit post.
- A **thread** is one top-level (root) comment on a post, together with all of its replies.
- A **document** is one thread as stored in Qdrant: the post's title and body, followed by the
  thread's comment tree. A post with several top-level comments becomes several documents.

## Keeping these documents accurate

Update the document that describes a behaviour in the same pull request that changes it. The
[comment rules in CONTRIBUTING.md](../.github/CONTRIBUTING.md#comments-and-documentation) apply
here too: describe what the code does now, and keep measurements and history in commits and
issues.
