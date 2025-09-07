import { toast } from "sonner"

export default async function Query(question) {
	const url = new URL(process.env.NEXT_PUBLIC_HF_API_URL)
	url.pathname = "/ask"

	const resp = await fetch(url, {
		method: "POST",
		headers: {
			"Content-Type": "application/json",
		},
		body: JSON.stringify({
			query: question,
		}),
	})

	if (resp.ok) {
		return await resp.json()
	}

	toast.error("An error occurred. Check browser console for logs.")
	console.error(resp)
}
