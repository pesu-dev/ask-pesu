export default async function Query(
	question,
	thinkingMode = true,
	chatHistory = [],
	{ onToken, onStep, onDone, onFirstByte, onError } = {}
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
			const err = {
				status: false,
				httpStatus: resp.status,
			}
			onError?.(err)
			return err
		}

		if (!resp.body) {
			const err = {
				status: false,
				message: "Empty response body",
				httpStatus: resp.status,
			}
			onError?.(err)
			return err
		}

		const reader = resp.body.getReader()
		const decoder = new TextDecoder()

		let buffer = ""
		let firstByteSeen = false
		let doneEventSeen = false

		const processLine = (line) => {
			const trimmed = line.trim()
			if (!trimmed) return

			let data
			try {
				data = JSON.parse(trimmed)
			} catch (parseError) {
				console.warn(
					"Skipping malformed stream line:",
					trimmed,
					parseError
				)
				return
			}

			if (data.type === "token") onToken?.(data.content || "")
			if (data.type === "step") onStep?.(data.content || "")
			if (data.type === "done") {
				doneEventSeen = true
				onDone?.()
			}
		}

		while (true) {
			const { done, value } = await reader.read()
			if (done) break

			if (!firstByteSeen && value && value.byteLength > 0) {
				firstByteSeen = true
				onFirstByte?.()
			}

			buffer += decoder.decode(value, { stream: true })

			const lines = buffer.split("\n")
			buffer = lines.pop() || ""

			for (const line of lines) {
				processLine(line)
			}
		}

		// Flush decoder and trailing buffer for safety.
		buffer += decoder.decode()
		if (buffer.trim()) {
			processLine(buffer)
		}

		// Fallback if backend closes stream without explicit done event.
		if (!doneEventSeen) {
			onDone?.()
		}

		return { status: true }
	} catch (err) {
		console.error("Network error:", err)

		const errorPayload = {
			status: false,
			message: "Network error",
			httpStatus: 0,
		}
		onError?.(errorPayload)

		return errorPayload
	}
}
