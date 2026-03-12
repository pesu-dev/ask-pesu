export default async function Query(
  question,
  thinkingMode = false,
  chatHistory = [],
  { onToken, onStep, onDone } = {}
) {
  try {
    const resp = await fetch(`/ask`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        query: question,
        thinking: thinkingMode,
        history: chatHistory,
      }),
    })

    if (!resp.ok) {
      return {
        status: false,
        httpStatus: resp.status,
      }
    }

    const reader = resp.body.getReader()
    const decoder = new TextDecoder()

    let buffer = ""

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value)

      const lines = buffer.split("\n")
      buffer = lines.pop()

      for (const line of lines) {
        if (!line.trim()) continue

        const data = JSON.parse(line)

        if (data.type === "token") {
          onToken?.(data.content)
        }

        if (data.type === "step") {
          onStep?.(data.content)
        }

        if (data.type === "done") {
          onDone?.()
        }
      }
    }

    return { status: true }

  } catch (err) {
    console.error("Network error:", err)

    return {
      status: false,
      message: "Network error",
      httpStatus: 0,
    }
  }
}
