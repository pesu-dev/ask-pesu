import { toast } from "sonner"

export default async function Query(question) {
	const url = new URL(process.env.NEXT_PUBLIC_URL)
	url.pathname = "/ask"
	url.searchParams.append("query", question)

	const resp = await fetch(url)

	if (resp.ok) {
		return await resp.json()
	}

	toast.error("An error occurred. Check browser console for logs.")
	console.error(resp)
}
