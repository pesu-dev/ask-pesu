# askPESU

A Retrieval-Augmented Generation (RAG) pipeline built over community-sourced data from r/PESU.
Provides a QA bot for PES University students via an API endpoint and a website (to be added).


API Endpoint:
```bash
https://unknownpixel-askpesu.hf.space/ask?query={query}
```

> [!WARNING]
> askPESU is an independent student project, not affiliated with PES University. Answers are generated from public discussions and may not always represent official policies.

## Highlights

- RAG-powered: Combines retrieval from PESU-related discussions with LLM generation.
- Simple REST API: Just send a query and get an answer back in JSON.
- Community-driven: Data built from real student experiences on r/PESU.
- Lightweight Deployment: Hosted on Hugging Face Spaces for ease of access.

## API

### Overview:

Endpoint:
```bash
GET /ask?query={query}
```

**Parameters**:
- query (string, required) – Your question.

**Returns** (JSON):
- query – The original question.
- answer – The generated answer.

### Example code

```bash
pip install requests
```

```py
import requests

query = "How do I register for electives?"
url = f"https://unknownpixel-askpesu.hf.space/ask?query={query}"

response = requests.get(url)
print(response.json())
```

Output (JSON):
```json
{
  "query":"what%is%pes",
  "answer":"PES, also referred to as PESU, is an engineering college/university. It is considered a top engineering college in Karnataka."
}
```

### From terminal

```bash
curl "https://unknownpixel-askpesu.hf.space/ask?query=What%is%pesu"
```

## Contributors
<a href="https://github.com/pesu-dev/ask-pesu/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=pesu-dev/ask-pesu" />
</a>

Made with [contrib.rocks](https://contrib.rocks).

## License:

MIT License. See [LICENSE](LICENSE) for full text.
