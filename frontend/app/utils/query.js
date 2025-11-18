import { toast } from "sonner"

<<<<<<< Updated upstream
export default async function Query(question, thinkingMode = false) {
=======
export default async function Query(question, thinking = false) {
>>>>>>> Stashed changes
	try {
		const resp = await fetch(`/ask`, {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
			},
<<<<<<< Updated upstream
			body: JSON.stringify({ query: question, thinking: thinkingMode }),
=======
			body: JSON.stringify({ query: question, thinking: thinking }),
>>>>>>> Stashed changes
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
