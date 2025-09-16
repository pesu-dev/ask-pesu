"use client"

import { useState, useEffect, useRef, useCallback } from "react"
import UserPrompt from "@/components/custom_ui/userPrompt"
import QueryInput from "@/components/custom_ui/queryInput"
import LlmResponse from "@/components/custom_ui/llmResponse"
import Query from "./utils/query"
import { toast } from "sonner"

export default function Home() {
	const [query, setQuery] = useState("")
	const [history, setHistory] = useState([])
	const [inQueueQuery, setInQueueQuery] = useState("")
	const [loading, setLoading] = useState(false)
	const chatEndRef = useRef(null)

	// Auto-scroll to bottom on new message
	useEffect(() => {
		chatEndRef.current?.scrollIntoView({ behavior: "smooth" })
	}, [history, inQueueQuery, chatEndRef])

	const handleEditQuery = useCallback((query) => {
		setQuery(query)
	}, [])

	const inputRef = useRef(null)
	const [highlight, setHighlight] = useState(false)

	// Remove highlight on blur
	const handleBlur = () => setHighlight(false)

	const handleQuery = useCallback(async () => {
		if (!query.trim()) {
			toast.warning("You can't query an empty question.")
			return
		}

		setLoading(true)
		setInQueueQuery(query)

		const data = await Query(query)
		console.info(data)

		setInQueueQuery(null)
		setQuery("")

		if (data) {
			setHistory((prev) => [
				...prev,
				{
					query,
					answer: data.answer,
				},
			])
		}

		setLoading(false)
	}, [query, setLoading, setInQueueQuery, setHistory, setQuery])

	return (
		<div className="relative bg-background w-screen h-screen flex flex-col">
			{/* Chat Window */}
			<div className="flex-1 w-full max-w-5xl mx-auto px-4 py-6 overflow-y-auto hide-scrollbar">
				{/* Past Queries */}
				{history.map((row, i) => (
					<div key={i} className="mb-6">
						<UserPrompt
							query={row.query}
							handleEditQuery={handleEditQuery}
						/>
						<LlmResponse answer={row.answer} />
					</div>
				))}

				{/* Pending Query */}
				{inQueueQuery && (
					<div className="mb-6">
						<UserPrompt query={inQueueQuery} />

						<div className="flex justify-start mt-3">
							<div className="bg-muted px-4 py-3 rounded-2xl max-w-[75%] text-neutral-500 shadow">
								Thinking...
							</div>
						</div>
					</div>
				)}

				<div ref={chatEndRef} className="mb-[10vh]" />
			</div>

			{/* Input Box For New Queries */}
			<div className="absolute bottom-10 w-full ">
				<QueryInput
					query={query}
					setQuery={setQuery}
					loading={loading}
					handleQuery={handleQuery}
				/>
			</div>
		</div>
	)
}
