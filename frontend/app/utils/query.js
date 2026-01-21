export default async function Query(
	question,
	thinkingMode = false,
	chatHistory = []
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

		const data = await resp.json()

		if (resp.ok) {
			return data
		}

		// Return error response with status code
		return {
			...data,
			httpStatus: resp.status,
		}
	} catch (err) {
		console.error("Network error:", err)
		return {
			status: false,
			message: "Network error. Please check your connection.",
			httpStatus: 0,
		}
	}
}
