import os
import json
import time
import sys
import uuid
import shutil
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from dotenv import load_dotenv


data_dir = "processed_data/"
completed_dir = "completed/"
files = os.listdir(data_dir)
num_files = len(files)
collection = ""
BATCH_SIZE = 64


load_dotenv(".env")
os.makedirs(completed_dir, exist_ok=True)


embeddings = HuggingFaceEmbeddings(
    model_kwargs={"device": "mps"},
    model_name="Alibaba-NLP/gte-modernbert-base",
)

client = QdrantClient(
    url=os.getenv("QDRANT_URL"),
    api_key=os.getenv("QDRANT_API_KEY"),
    timeout=120.0,
)

vector_store = QdrantVectorStore(
    client=client,
    collection_name=collection,
    embedding=embeddings,
)


def convert_to_uuid(string: str) -> str:
    """Convert Reddit comment ID to UUID."""
    return str(uuid.uuid5(uuid.NAMESPACE_OID, string))


def get_all_ids(client: QdrantClient, collection: str):
    all_ids = set()
    offset = None
    while True:
        points, next_page = client.scroll(
            collection_name=collection,
            with_payload=False,
            with_vectors=False,
            offset=offset,
            limit=10000,
        )
        all_ids.update(p.id for p in points)
        if next_page is None:
            break
        offset = next_page
    return all_ids


def flush_batch(vector_store, existing_ids, batch, inserted_ids):
    if not batch:
        return 0
    texts = [t for t, _, _ in batch]
    metadatas = [m for _, m, _ in batch]
    ids = [c for _, _, c in batch]
    vector_store.add_texts(texts=texts, metadatas=metadatas, ids=ids)
    existing_ids.update(ids)
    inserted_ids.extend(ids)
    batch.clear()
    return len(ids)


def print_progress(counter, num_files, t0):
    elapsed = time.time() - t0
    pct = counter / num_files * 100
    rate = counter / elapsed if elapsed else 0
    eta = (num_files - counter) / rate if rate else 0
    bar_w = 30
    filled = int(bar_w * counter / num_files)
    bar = "#" * filled + "-" * (bar_w - filled)
    sys.stdout.write(
        f"\r[{bar}] {pct:5.1f}% | {counter}/{num_files} | {elapsed:5.0f}s elapsed | ETA {eta:5.0f}s"
    )
    sys.stdout.flush()


counter = 0
inserted = 0
skipped = 0
inserted_ids = []
batch = []
t0 = time.time()

print("Fetching existing point IDs from Qdrant ...")
existing_ids = get_all_ids(client, collection)
print(f"Found {len(existing_ids)} existing points")

print_progress(0, num_files, t0)

for file in files:
    file_path = os.path.join(data_dir, file)
    json_file = open(f"processed_posts/{file}", "r")
    data = json.load(json_file)
    for comment in data["comments"]:
        root_comment_id = comment["id"]
        chunk = (
            f"TITLE: {data['title']}\n"
            f"CONTENT: {data['content']}\n"
            f"COMMENT TREE: {comment['body']}"
        )
        metadata = data["metadata"]
        chunk_id = convert_to_uuid(root_comment_id)

        if chunk_id in existing_ids:
            skipped += 1
            continue

        batch.append((chunk, metadata, chunk_id))
        if len(batch) >= BATCH_SIZE:
            inserted += flush_batch(vector_store, existing_ids, batch, inserted_ids)

    # flush the remainder so each file is fully in the DB before moving it
    inserted += flush_batch(vector_store, existing_ids, batch, inserted_ids)
    shutil.move(file_path, os.path.join(completed_dir, file))
    counter += 1
    print_progress(counter, num_files, t0)

print()
print(f"Files processed: {num_files} | Inserted: {inserted} | Skipped (already in DB): {skipped}")

missing = []
for i in range(0, len(inserted_ids), 100):
    batch_ids = inserted_ids[i : i + 100]
    results = client.retrieve(collection_name=collection, ids=batch_ids)
    found_ids = {point.id for point in results}
    for pid in batch_ids:
        if pid not in found_ids:
            missing.append(pid)

print(f"Missing points after insert: {len(missing)}")
if missing:
    with open("missing_points.json", "w") as f:
        json.dump(missing, f, indent=2)
    print("Missing point UUIDs written to missing_points.json")