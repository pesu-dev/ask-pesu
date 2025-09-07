"use client"

import { useCallback, useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ArrowUp } from "lucide-react"
import Query from "./utils/query"
import { toast } from "sonner"

export default function Home() {
	const [query, setQuery] = useState("")
	const [history, setHistory] = useState([])
	const [inQueueQuery, setInQueueQuery] = useState(null)
	const [loading, setLoading] = useState(false)

	const handleQuery = useCallback(async () => {
		if (!query.trim()) {
			toast.warning("You can't query an empty question.")
		}

		setLoading(true)

		setInQueueQuery(query)

		const data = await Query(query)

		setInQueueQuery("")
		setQuery("")

		if (data) {
			setHistory((prev) => {
				return [...prev, data]
			})
		}

		setLoading(false)
	}, [query])

	return (
		<div className="bg-background w-screen h-screen">
			<div className="w-[75vw] h-[90vh] m-auto overflow-y-scroll hide-scrollbar">
				{history.map((row, i) => {
					return (
						<div key={i}>
							<div className="bg-accent p-2 rounded-xl w-max my-10">
								{row.query}
							</div>
							<div className="text-lg/relaxed">{row.answer}</div>
						</div>
					)
				})}
				{inQueueQuery ? (
					<div>
						<div className="bg-accent p-2 rounded-xl w-max my-10">
							{inQueueQuery}
						</div>
						<div className="text-lg/relaxed text-neutral-500">
							Thinking...
						</div>
					</div>
				) : null}
			</div>
			<div className="w-full h-[10vh] border-t-1 border-t-neutral-500">
				<div className="m-auto w-[50vw] flex flex-nowrap pt-6">
					<Input
						disabled={loading}
						className="rounded-r-none"
						value={query}
						onChange={(e) => {
							setQuery(e.target.value)
						}}
					/>
					<Button
						disabled={loading}
						className="rounded-l-none bg-sky-50/80 hover:bg-sky-100/80 cursor-pointer"
						onClick={handleQuery}
					>
						<ArrowUp />
					</Button>
				</div>
			</div>
		</div>
	)
}
