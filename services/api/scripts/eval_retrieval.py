"""Measure retrieval quality against the live collection, so ranking changes are falsifiable.

Nothing else in this repository can answer "did that make retrieval better?". The
contract checks catch a writer/reader mismatch and the container tests catch a
broken image, but neither can tell a good ranking from a bad one. This script
exists to put a number on it before and after a change.

It is **read-only**: it opens the collection, runs searches, and prints. It never
writes, and it never calls an LLM -- there is no query rewriting and no
multi-query expansion here, because those add variance that would drown the
signal this is trying to isolate. What it measures is the retrieval stage alone,
optionally followed by the cross-encoder, which is where ranking changes land.

    uv run python scripts/eval_retrieval.py --mode dense
    uv run python scripts/eval_retrieval.py --mode hybrid --rerank

Ground truth is the two question sets below: real r/PESU threads, each paired
with a question worded the way somebody would actually ask it. Every thread was
read before it was labelled.

They are kept separate because they measure different things, and the split is
what makes the dense/hybrid comparison meaningful:

- ``NATURAL`` asks in plain English, deliberately paraphrased away from the
  thread's own title and avoiding campus jargon. Scoring against a verbatim
  title would hand BM25 a free lexical match; this is the honest case.
- ``JARGON`` asks the way students actually type -- ``CSE``, ``PESSAT``, ``T1``,
  ``SGPA``, ``CGPA``, ``capstone``. These are exact tokens that appear in the
  corpus and cannot be reached by paraphrase.

Run both sets against both modes and the split does the arguing. Hybrid tends to
be a wash on NATURAL and clearly ahead on JARGON, which is the case for hybrid
retrieval and also why the query rewriter expands abbreviations *alongside* the
original rather than replacing it: rewriting ``CSE`` into ``Computer Science
Engineering`` turns a JARGON query into a NATURAL one and hands that gain back.

Two things to keep in mind before reading much into a small delta:

- **The collection is live.** ``services/db`` indexes new threads continuously,
  so the corpus grows underneath consecutive runs and a question can change rank
  with nothing else changed. The sets are small enough that one question moves
  the percentages noticeably, so compare runs taken close together and believe
  only differences of several questions.
- A question can legitimately be answered by more than one thread, so a miss is
  not necessarily a failure. These are numbers to beat, not to reach 100%.
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_huggingface.embeddings import HuggingFaceEmbeddings
from langchain_qdrant import QdrantVectorStore, RetrievalMode
from qdrant_client import QdrantClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import contract as contract_mod  # noqa: E402

load_dotenv()

# (question, post_id that answers it). The post id is what is compared, not the
# permalink: `permalink` is the submission's, so every document from one post
# carries the same one, and post id is the same comparison with less to go wrong.
#
# Plain English, paraphrased away from the thread's title and avoiding jargon.
NATURAL: tuple[tuple[str, str], ...] = (
    ("If I already have a tier 3 offer, can I still interview at tier 1 companies?", "1kq6d08"),
    ("If I accept a tier 2 internship that converts to a full time role, what offers can I still take?", "1n9ud66"),
    ("Are grade cutoffs at PES fixed, or moved depending on how the batch performs?", "1phgfw0"),
    ("How many credits do I need in total before I can graduate?", "1dpmntf"),
    ("What are special topic courses and how many credits is each one worth?", "1dnbx90"),
    ("What CGPA do I need to change my branch after first year?", "1du81sy"),
    ("Is the AIML branch actually different from regular computer science in the first two years?", "1cn3uab"),
    ("Will choosing AIML help me get a machine learning job instead of a normal software one?", "147gamv"),
    ("How is computer science at the Electronic City campus compared to electronics?", "pcdla9"),
    ("What ranks do Ring Road and Electronic City close at for computer science?", "1cpg2rr"),
    ("What is the girls hostel at south campus like, how is the hygiene?", "1e2jzh3"),
    ("Are mechanical engineering placements decent here or should I pick another college?", "1kwugh3"),
    ("Should I give up an NIT seat to join PES for computer science?", "1jkwkb9"),
    ("After a computer science degree, is it better to work first or go straight to a masters?", "1mypvco"),
    ("What does the MBA cost per year if I get in through PGCET?", "18dlv2q"),
    ("After KCET seat allotment, what reporting formalities do I still have to complete?", "1fevmn0"),
    ("What happens if I want to surrender the seat I was allotted?", "1e941q1"),
    ("Are the textbooks recommended for computer science courses actually worth reading?", "12w02qd"),
    ("Can I define my own capstone project or must I pick one the professors listed?", "10qqofb"),
    ("What is actually expected in the literature survey part of a project?", "110r88y"),
    ("How do the different research labs here compare if I want an internship?", "1d4zz80"),
    ("How do I build a portfolio good enough to land a UI UX internship?", "1cq89yo"),
    ("As an electronics student, which electives should I pick to improve my placement chances?", "1pw4ez0"),
    ("How difficult is second year and what does it do to your GPA?", "1ikhflo"),
    ("How much does luck actually matter in getting placed?", "1n17tp1"),
    ("Is a summer research lab internship better than grinding DSA for placements?", "1qefh9z"),
)

# The same corpus, asked the way students actually type: abbreviations, course
# codes and tier names that appear verbatim in the threads. This is the set
# hybrid retrieval exists for -- no amount of paraphrase reaches these tokens.
JARGON: tuple[tuple[str, str], ...] = (
    ("PESU placement policy T1 T2 T3 offer rules", "1kq6d08"),
    ("T2 intern plus FTE offer quota placements", "1n9ud66"),
    ("relative grading COE grade cutoff", "1phgfw0"),
    ("160 credits required to graduate", "1dpmntf"),
    ("special topics 2 credit courses", "1dnbx90"),
    ("branch change CGPA cutoff", "1du81sy"),
    ("AIML vs CSE", "1cn3uab"),
    ("CSE EC campus vs RR campus KCET closing rank", "1cpg2rr"),
    ("KCET CPAIC portal college report", "1fevmn0"),
    ("MBA PGCET fees", "18dlv2q"),
    ("ECE electives placements", "1pw4ez0"),
    ("capstone project profs", "10qqofb"),
    ("SGPA CGPA second year subjects WT DDCO", "1ikhflo"),
    ("girls hostel south campus hygiene", "1e2jzh3"),
    ("mech placements RV BMS MSRIT", "1kwugh3"),
    ("seat surrender IIIT NIT", "1e941q1"),
)

QUESTION_SETS: dict[str, tuple[tuple[str, str], ...]] = {"natural": NATURAL, "jargon": JARGON}


def build_store(contract: contract_mod.Contract, client: QdrantClient, mode: str) -> QdrantVectorStore:
    """Open the collection for reading in the requested retrieval mode.

    Args:
        contract: The loaded collection contract.
        client: A Qdrant client.
        mode: ``dense`` or ``hybrid``.

    Returns:
        A vector store. In hybrid mode Qdrant fuses the dense and sparse
        rankings with Reciprocal Rank Fusion, so the scores it returns are RRF
        scores, not cosine similarities -- they are not comparable across modes
        and this script never compares them.
    """
    embeddings = HuggingFaceEmbeddings(model_name=contract.model)
    contract_mod.validate_embedding(contract, embeddings)

    if mode == "dense":
        return QdrantVectorStore(
            client=client,
            collection_name=contract.name,
            embedding=embeddings,
            vector_name=contract.vector_name,
        )

    if not contract.sparse_vector_name:
        raise SystemExit("conf/collection.yaml declares no sparse vector, so hybrid retrieval is not available.")

    from langchain_qdrant import FastEmbedSparse

    return QdrantVectorStore(
        client=client,
        collection_name=contract.name,
        embedding=embeddings,
        vector_name=contract.vector_name,
        sparse_embedding=FastEmbedSparse(model_name=contract.sparse_model),
        sparse_vector_name=contract.sparse_vector_name,
        retrieval_mode=RetrievalMode.HYBRID,
    )


def rank_of(post_ids: list[str], expected: str) -> int | None:
    """Return the 1-based position of the first document from ``expected``, or None."""
    for position, post_id in enumerate(post_ids, start=1):
        if post_id == expected:
            return position
    return None


def main() -> int:
    """Run every question and report recall and MRR."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=("dense", "hybrid"), default="dense", help="Retrieval mode to measure.")
    parser.add_argument("--k", type=int, default=10, help="Documents to retrieve per question.")
    parser.add_argument(
        "--collection",
        default=None,
        help="Override $QDRANT_COLLECTION. Use the populated collection; this script only reads.",
    )
    parser.add_argument("--rerank", action="store_true", help="Also apply the cross-encoder and report both rankings.")
    parser.add_argument(
        "--rerank-model",
        default="cross-encoder/ms-marco-MiniLM-L6-v2",
        help="Cross-encoder for --rerank.",
    )
    parser.add_argument(
        "--set",
        choices=("natural", "jargon", "all"),
        default="all",
        help="Which question set to run. They measure different things; see the module docstring.",
    )
    parser.add_argument("--verbose", action="store_true", help="Print the rank of every question, not just misses.")
    args = parser.parse_args()

    contract = contract_mod.load()
    if args.collection:
        contract = contract._replace(name=args.collection)

    client = QdrantClient(url=os.getenv("QDRANT_URL"), api_key=os.getenv("QDRANT_API_KEY"))
    contract_mod.validate_collection(contract, client)
    print(f"collection={contract.name!r} mode={args.mode} k={args.k} rerank={args.rerank}")

    store = build_store(contract, client, args.mode)

    cross_encoder = None
    if args.rerank:
        import torch
        from sentence_transformers import CrossEncoder

        cross_encoder = CrossEncoder(args.rerank_model, activation_fn=torch.nn.Sigmoid())

    def report(label: str, values: list[int | None]) -> None:
        total = len(values)
        mrr = sum(1.0 / r for r in values if r) / total
        cuts = "  ".join(
            f"r@{cut}={sum(1 for r in values if r and r <= cut)}/{total}" for cut in (1, 3, 5, 10) if cut <= args.k
        )
        print(f"  {label:<28} {cuts}  MRR={mrr:.3f}")

    chosen = QUESTION_SETS if args.set == "all" else {args.set: QUESTION_SETS[args.set]}
    for set_name, questions in chosen.items():
        ranks: list[int | None] = []
        reranked_ranks: list[int | None] = []
        for question, expected in questions:
            docs = [doc for doc, _ in store.similarity_search_with_score(question, k=args.k)]
            rank = rank_of([d.metadata.get("post_id") for d in docs], expected)
            ranks.append(rank)

            line = f"  {'ok  ' if rank else 'MISS'} rank={str(rank or '-'):>3}"
            if cross_encoder is not None and docs:
                scores = cross_encoder.predict([[question, d.page_content] for d in docs])
                order = sorted(zip(docs, scores), key=lambda pair: float(pair[1]), reverse=True)
                reranked = rank_of([d.metadata.get("post_id") for d, _ in order], expected)
                reranked_ranks.append(reranked)
                line += f" -> {str(reranked or '-'):>3}"
            if args.verbose or rank is None:
                print(f"{line}  {question[:70]}")

        print(f"\n{set_name} ({len(questions)} questions)")
        report(f"{args.mode}", ranks)
        if reranked_ranks:
            report(f"{args.mode} + cross-encoder", reranked_ranks)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
