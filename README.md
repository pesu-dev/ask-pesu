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

[![Docker Image Build](https://github.com/pesu-dev/ask-pesu/actions/workflows/docker.yaml/badge.svg)](https://github.com/pesu-dev/ask-pesu/actions/workflows/docker.yaml)
[![Pre-Commit Checks](https://github.com/pesu-dev/ask-pesu/actions/workflows/pre-commit.yaml/badge.svg)](https://github.com/pesu-dev/ask-pesu/actions/workflows/pre-commit.yaml)
[![Lint](https://github.com/pesu-dev/ask-pesu/actions/workflows/lint.yaml/badge.svg)](https://github.com/pesu-dev/ask-pesu/actions/workflows/lint.yaml)
[![Deploy](https://github.com/pesu-dev/ask-pesu/actions/workflows/deploy-prod.yaml/badge.svg)](https://github.com/pesu-dev/ask-pesu/actions/workflows/deploy-prod.yaml)

[![Docker Automated build](https://img.shields.io/docker/automated/aditeyabaral/pesu-auth?logo=docker)](https://hub.docker.com/r/aditeyabaral/pesu-auth/builds)
[![Docker Image Version (tag)](https://img.shields.io/docker/v/aditeyabaral/pesu-auth/latest?logo=docker&label=build%20commit)](https://hub.docker.com/r/aditeyabaral/pesu-auth/tags)
[![Docker Image Size (tag)](https://img.shields.io/docker/image-size/aditeyabaral/pesu-auth/latest?logo=docker)](https://hub.docker.com/r/aditeyabaral/pesu-auth)

A RAG Pipeline to answer questions based on PESU.

The API is secure and protects user privacy by not storing any user credentials. It only validates credentials and
returns the user's profile information. No personal data is stored.

## AskPESU LIVE Deployment

* You can access the AskPESU API endpoints [here](https://huggingface.co/spaces/pesu-dev/askpesu-dev).

## How to run AskPESU locally

Running AskPESU locally is simple. Clone the repository and follow the steps below to get started.

### Running with Docker

This is the easiest and recommended way to run the API locally. Ensure you have Docker installed on your system. Run the
following commands to start the API.

1. Build the Docker image either from the source code.

    ```bash
    docker build . --tag ask-pesu
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

## How to use the PESUAuth API

The API provides multiple endpoints for authentication, documentation, and monitoring.

| **Endpoint**    | **Method** | **Description**                                        |
|-----------------|------------|--------------------------------------------------------|
| `/`             | `GET`      | Serves the interactive API documentation (Swagger UI). |
| `/authenticate` | `POST`     | Authenticates a user using their PESU credentials.     |
| `/health`       | `GET`      | A health check endpoint to monitor the API's status.   |
| `/readme`       | `GET`      | Redirects to the project's official GitHub repository. |

### `/authenticate`

You can send a request to the `/authenticate` endpoint with the user's credentials and the API will return a JSON
object, with the user's profile information if requested.

#### Request Parameters

| **Parameter** | **Optional** | **Type**    | **Default** | **Description**                                                                                 |
|---------------|--------------|-------------|-------------|-------------------------------------------------------------------------------------------------|
| `username`    | No           | `str`       |             | The user's SRN or PRN                                                                           |
| `password`    | No           | `str`       |             | The user's password                                                                             |
| `profile`     | Yes          | `boolean`   | `False`     | Whether to fetch profile information                                                            |
| `fields`      | Yes          | `list[str]` | `None`      | Which fields to fetch from the profile information. If not provided, all fields will be fetched |

#### Response Object

On authentication, it returns the following parameters in a JSON object. If the authentication was successful and
profile data was requested, the response's `profile` key will store a dictionary with a user's profile information.
**On an unsuccessful sign-in, this field will not exist**.

| **Field**   | **Type**        | **Description**                                                          |
|-------------|-----------------|--------------------------------------------------------------------------|
| `status`    | `boolean`       | A flag indicating whether the overall request was successful             |
| `profile`   | `ProfileObject` | A nested map storing the profile information, returned only if requested |
| `message`   | `str`           | A message that provides information corresponding to the status          |
| `timestamp` | `datetime`      | A timezone offset timestamp indicating the time of authentication        |

##### `ProfileObject`

This object contains the user's profile information, which is returned only if the `profile` parameter is set to `True`.
If the authentication fails, this field will not be present in the response.

| **Field**     | **Description**                                        |
|---------------|--------------------------------------------------------|
| `name`        | Name of the user                                       |
| `prn`         | PRN of the user                                        |
| `srn`         | SRN of the user                                        |
| `program`     | Academic program that the user is enrolled into        |
| `branch`      | Complete name of the branch that the user is pursuing  |
| `semester`    | Current semester that the user is in                   |
| `section`     | Section of the user                                    |
| `email`       | Email address of the user registered with PESU         |
| `phone`       | Phone number of the user registered with PESU          |
| `campus_code` | The integer code of the campus (1 for RR and 2 for EC) |
| `campus`      | Abbreviation of the user's campus name                 |

### `/health`

This endpoint can be used to check the health of the API. It's useful for monitoring and uptime checks. This endpoint
does not take any request parameters.

#### Response Object

| **Field** | **Type**   | **Description**                                                   |
|-----------|------------|-------------------------------------------------------------------|
| `status`  | `str`      | `true` if healthy, `false` if there was an error                  |
| `message` | `str`      | "ok" if healthy, error message otherwise                          |
| `timestamp` | `string` | A timezone offset timestamp indicating the time of authentication |

### `/readme`

This endpoint redirects to the project's official GitHub repository. This endpoint does not take any request parameters.

### Integrating your application with the PESUAuth API

Here are some examples of how you can integrate your application with the PESUAuth API using Python and cURL.

#### Python

##### Request

```python
import requests

data = {
    "username": "your SRN or PRN here",
    "password": "your password here",
    "profile": True,  # Optional, defaults to False
}

response = requests.post("http://localhost:5000/authenticate", json=data)
print(response.json())
```

##### Response

```json
{
  "status": true,
  "profile": {
    "name": "Johnny Blaze",
    "prn": "PES1201800001",
    "srn": "PES1201800001",
    "program": "Bachelor of Technology",
    "branch": "Computer Science and Engineering",
    "semester": "NA",
    "section": "NA",
    "email": "johnnyblaze@gmail.com",
    "phone": "1234567890",
    "campus_code": 1,
    "campus": "RR"
  },
  "message": "Login successful.",
  "timestamp": "2024-07-28 22:30:10.103368+05:30"
}
```

#### cURL

##### Request

```bash
curl -X POST http://localhost:5000/authenticate \
-H "Content-Type: application/json" \
-d '{
    "username": "your SRN or PRN here",
    "password": "your password here"
}'
```

#### Response

```json
{
  "status": true,
  "message": "Login successful.",
  "timestamp": "2024-07-28 22:30:10.103368+05:30"
}
```

## Contributing to PESUAuth

Made with ❤️ by

[![Contributors](https://contrib.rocks/image?repo=pesu-dev/ask-pesu&nocache=1)](https://github.com/pesu-dev/ask-pesu/graphs/contributors)

*Powered by [contrib.rocks](https://contrib.rocks)*

If you'd like to contribute, please follow our [contribution guidelines](.github/CONTRIBUTING.md).
