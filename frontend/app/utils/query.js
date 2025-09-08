import { toast } from "sonner"

export default async function Query(question) {
	try {
		const resp = await fetch("/ask", {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
			},
			body: JSON.stringify({ query: question }),
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
