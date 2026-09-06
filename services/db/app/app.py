import os
import praw
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from langchain_qdrant import QdrantVectorStore
from langchain_community.embeddings import HuggingFaceEmbeddings
from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams
import threading
from app.utils import build_thread_string, convert_to_uuid
import uvicorn
from dotenv import load_dotenv
import traceback


app = FastAPI()

vector_store = None
reddit = None
subreddit = None
collection_name = "ask-pesu"
client_id = os.getenv("reddit_client_id")
client_secret = os.getenv("reddit_client_secret")
qdrant_url = os.getenv("qdrant_url")
qdrant_api_key = os.getenv("qdrant_api_key")


def update_chunk(chunk_id: str, text: str, metadata: dict):
    """Overwrite if chunk exists, else add to Qdrant."""
    vector_store.add_texts(
        texts=[text],
        metadatas=[metadata],
        ids=[chunk_id],
    )


def get_root_comment(comment):
    """Get root comment of the comment thread."""
    parent = comment
    while not parent.is_root:
        parent = parent.parent()
    return parent


def listen_comments():
    """Main listener loop for new comments."""
    while True:
        try:
            for comment in subreddit.stream.comments(skip_existing=True):
                author = str(comment.author).lower()
                if author == "automoderator":
                    continue

                submission = comment.submission
                root_comment = get_root_comment(comment)

                print("Root comment:", root_comment.body)
                print("Root ID:", root_comment.id)

                chunk = (
                    f"TITLE: {submission.title}\n"
                    f"CONTENT: {submission.selftext}\n"
                    f"COMMENT TREE: {build_thread_string(root_comment)}"
                )

                metadata = {
                    "root_comment_id": root_comment.id,
                    "post_id": submission.id,
                    "author": str(submission.author) if submission.author else None,
                    "url": submission.url,
                    "permalink": "https://reddit.com" + submission.permalink,
                    "score": submission.score,
                    "upvote_ratio": submission.upvote_ratio,
                    "created_utc": submission.created_utc,
                    "flair": submission.link_flair_text,
                    "nsfw": submission.over_18,
                }

                update_chunk(
                    convert_to_uuid(root_comment.id), chunk, metadata
                )  # using UUID as Qdrant expects UUID as the point/vector id in the DB
                print("Updated chunk.")
        except Exception:
            print("Unexpected error in listener:")
            traceback.print_exc()


def background_listener():
    """Run listener in a thread so FastAPI stays responsive."""
    thread = threading.Thread(target=listen_comments, daemon=True)
    thread.start()


@app.on_event("startup")
async def startup_event():
    global vector_store, reddit, subreddit

    client = QdrantClient(
        url=qdrant_url,
        api_key=qdrant_api_key,
        timeout=120.0,
    )

    embeddings = HuggingFaceEmbeddings(
        model_name="Alibaba-NLP/gte-modernbert-base",
        # model_kwargs={"device": "cpu"}
    )

    try:
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=768, distance="Cosine"),
        )
        print("Collection created")
    except Exception:
        print("Collection already exists")

    vector_store = QdrantVectorStore(
        client=client,
        collection_name=collection_name,
        embedding=embeddings,
    )

    reddit = praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent="langchain-reddit-loader",
    )
    subreddit = reddit.subreddit("PESU")

    background_listener()
    print("Background listener started.")


@app.get("/health")
async def health():
    return JSONResponse({"status": "ok"})


if __name__ == "__main__":
    # load environment variables from .env file
    load_dotenv()

    # Run the app
    uvicorn.run("app.app:app", host="0.0.0.0", port=7860)
