export default async function Query(
	question,
	thinkingMode = false,
	chatHistory = []
) {
	try {
		const API_URL = process.env.NEXT_PUBLIC_DEV_API_URL;
		const url = `${API_URL}/ask`;
		//const url = `/ask`;
		const resp = await fetch(url, {
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

		if (resp.ok) {
			return await resp.json()
		}

		console.error("Request failed:", resp.status, resp.statusText)
	} catch (err) {
		console.error("Network error:", err)
	}
}
