# 0004. Retrieval and ranking have no recency weight

- **Status:** Accepted
- **Discussed in:** [#77](https://github.com/pesu-dev/ask-pesu/issues/77), [#90](https://github.com/pesu-dev/ask-pesu/pull/90), [#92](https://github.com/pesu-dev/ask-pesu/issues/92)

## Context

Some answers go out of date: fees, cutoffs, seat counts, placement figures. A weight favouring
newer documents would prefer recent answers to those questions.

On r/PESU, repeated questions are directed to existing threads, so many of the most referenced
answers are old, and much of the best-received content was written years ago. A weight applied to
every question would demote those answers.

## Decision

Retrieval and ranking do not weight documents by age. Age is reported instead:

- each `sources` entry carries `created_utc`, which the UI shows;
- each thread in the model's context is headed with the month it was posted;
- the system prompt tells the model to say when a time-sensitive fact was posted, and to lead with
  the most recent value when threads disagree.

## Consequences

- Whether a question needs recent sources is a property of the question, not the document. Any
  future recency handling has to classify the question.
- A hand-written list of volatile topics would be a configuration value derived from the corpus,
  which [0002](0002-no-corpus-derived-configuration.md) rules out.
- The date shown is the post's, not the reply's.

## Alternatives rejected

- **A global recency weight or decay.** It demotes the answers the community treats as
  authoritative, for every question.
