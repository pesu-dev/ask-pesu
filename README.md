---
title: Ask PESU
short_description: A RAG pipeline for question answering about PES University
emoji: 🦀
colorFrom: yellow
colorTo: red
sdk: docker
python_version: 3.12
app_file: app/app.py
app_port: 7860
fullWidth: true
header: mini
pinned: false
license: mit
disable_embedding: false
thumbnail: >-
  https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcT0VZcBflk0Q1auwPmjuXgoBj-VzFd9Iz_JfA&s
models:
- Alibaba-NLP/gte-modernbert-base
preload_from_hub:
- Alibaba-NLP/gte-modernbert-base
tags:
- rag
- assistant
- question answering
- pes university
---

# Ask PESU

[![Pre-Commit Checks](https://github.com/pesu-dev/ask-pesu/actions/workflows/pre-commit.yaml/badge.svg)](https://github.com/pesu-dev/ask-pesu/actions/workflows/pre-commit.yaml)
[![Lint](https://github.com/pesu-dev/ask-pesu/actions/workflows/lint.yaml/badge.svg)](https://github.com/pesu-dev/ask-pesu/actions/workflows/lint.yaml)
[![Deploy](https://github.com/pesu-dev/ask-pesu/actions/workflows/deploy-prod.yaml/badge.svg)](https://github.com/pesu-dev/ask-pesu/actions/workflows/deploy-prod.yaml)


A RAG Pipeline based API to answer questions based on PESU.

The API is secure and protects user privacy by not storing any user credentials. It only validates credentials and
returns the user's profile information. No personal data is stored.

## AskPESU API LIVE Deployment

* You can access the AskPESU API endpoints [here](https://huggingface.co/spaces/pesu-dev/askpesu-dev).

## How to run the AskPESU API locally

Running AskPESU locally is simple. Clone the repository and follow the steps below to get started.

### Running with Docker

This is the easiest and recommended way to run the API locally. Ensure you have Docker installed on your system. Run the
following commands to start the API.

1. Build the Docker image either from the source code.

    ```bash
    docker run --env-file .env -p 7860:7860 ask-pesu
    ```

2. Access the API at `http://localhost:5000/`

### Running without Docker

If you don't have Docker installed, you can run the API natively. Ensure you have Python 3.11 or higher
installed on your system. We recommend using a package manager like [`uv`](https://docs.astral.sh/uv/) to manage
dependencies.

1. Create a virtual environment using and activate it. Then, install the dependencies using the following commands.
    ```bash
    uv venv --python=3.11
    source .venv/bin/activate
    uv sync
    ```

2. Run the API using the following command.
    ```bash
    uv run python -m app.app
    ```

3. Access the API as previously mentioned on `http://localhost:7860/`

## How to use the AskPESU API

The API provides multiple endpoints for question answering and health checks.


| **Endpoint** | **Method** | **Description** |
|--------------|------------|------------------------------------------------|
| `/` | `GET` | Serves the frontend |
| `/ask` | `POST` | Answers questions about PES University using a RAG pipeline. |
| `/health` | `GET` | A health check endpoint to monitor the API's status. |

### `/ask`

You can send a request to the `/ask` endpoint with a user's query about PES University, and the API will return an answer generated using the RAG pipeline.

#### Request Parameters

| **Parameter** | **Optional** | **Type** | **Default** | **Description** |
|---------------|--------------|----------|-------------|-----------------|
| `query`       | No           | `str`    |             | The user's input question for the chatbot.              |

#### Response Object

On success, returns the following parameters in a JSON object.

| **Field**   | **Type**   | **Description**                                                        |
|-------------|------------|------------------------------------------------------------------------|
| `status`    | `boolean`  | A flag indicating whether the request was successful                   |
| `message`   | `str`      | A message describing the result                                        |
| `answer`    | `str`      | The answer generated for the user's query                              |
| `timestamp` | `string`   | A timezone offset timestamp indicating when the answer was generated   |
| `latency`   | `float`    | Time taken (in seconds) to generate the answer                        |

### `/health`

This endpoint can be used to check the health of the API. It's useful for monitoring and uptime checks. This endpoint does not take any request parameters.

#### Response Object

| **Field**   | **Type**   | **Description**                                                   |
|-------------|------------|-------------------------------------------------------------------|
| `status`    | `boolean`  | `true` if healthy, `false` if there was an error                  |
| `message`   | `str`      | "ok" if healthy, error message otherwise                          |
| `timestamp` | `string`   | A timezone offset timestamp indicating the time of the health check|


### Integrating your application with the AskPESU API

Here are some examples of how you can integrate your application with the AskPESU API using Python and cURL.

#### Python

##### Request

```python
import requests

data = {
    "query": "What is bootstrap at PES University?"
}

response = requests.post("http://localhost:7860/ask", json=data)
print(response.json())
```

##### Response

```json
{
  "status": true,
  "message": "Answer generated successfully.",
  "answer": "Bootstrap at PES University is a week-long (typically 5-day) series of activities for freshers, usually held before regular classes commence. Its main purpose is to help students socialize, make new friends, and network with batchmates and seniors. It also allows them to explore various academic branches through simple and engaging activities.",
  "timestamp": "2024-07-28T22:30:10.103368+05:30",
  "latency": 1.234
}
```

#### cURL

##### Request

```bash
curl -X POST http://localhost:7860/ask \
-H "Content-Type: application/json" \
-d '{
    "query": "What is bootstrap at PES University?"
}'
```

##### Response

```json
{
  "status": true,
  "message": "Answer generated successfully.",
  "answer": "Bootstrap at PES University is a week-long (typically 5-day) series of activities for freshers, usually held before regular classes commence. Its main purpose is to help students socialize, make new friends, and network with batchmates and seniors. It also allows them to explore various academic branches through simple and engaging activities.",
  "timestamp": "2024-07-28T22:30:10.103368+05:30",
  "latency": 1.234
}
```

## Contributing to AskPESU

Made with ❤️ by

[![Contributors](https://contrib.rocks/image?repo=pesu-dev/ask-pesu&nocache=1)](https://github.com/pesu-dev/ask-pesu/graphs/contributors)

*Powered by [contrib.rocks](https://contrib.rocks)*

If you'd like to contribute, please follow our [contribution guidelines](.github/CONTRIBUTING.md).
