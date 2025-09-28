import { toast } from "sonner"

export default async function Query(question, thinkingMode = false) {
	const API_URL = process.env.NEXT_PUBLIC_DEV_API_URL || "/ask"
	try {
		const resp = await fetch(`${API_URL}`, {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
			},
			body: JSON.stringify({ query: question, thinking: thinkingMode }),
		})

		if (resp.ok) {
			return await resp.json()
		}

		toast.error("An error occurred. Check browser console for logs.")
		console.error("Request failed:", resp.status, resp.statusText)
	} catch (err) {
		toast.error("Failed to reach the server.")
		console.error("Network error:", err)
	}
}
