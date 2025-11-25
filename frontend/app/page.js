"use client"

import { useState, useEffect, useRef, useCallback } from "react"
import UserPrompt from "@/components/customUi/userPrompt"
import QueryInput from "@/components/customUi/queryInput"
import LlmResponse from "@/components/customUi/llmResponse"
import Query from "./utils/query"
import { toast } from "sonner"
import useQuota from "@/hooks/useQuota"

export default function Home() {
	const [modelChoice, setModelChoice] = useState("primary") // This can either be 'primary' or 'thinking'
	const [query, setQuery] = useState("")
	const [history, setHistory] = useState([
		{
			query: "hi how are you doing?",
			answer: "I'm doing well, thank you for asking! How can I help you today?",
			model: "thinking",
		},
		{
			query: "give me a detailed review on studying a B-Tech degree at PESU",
			answer: "wait.",
			model: "primary",
		},
		{
			query: "hi how are you doing?",
			answer: "I'm doing well, thank you for asking! How can I help you today?",
			model: "thinking",
		},
		{
			query: "give me a detailed review on studying a B-Tech degree at PESU",
			answer: "wait.",
			model: "primary",
		},
	])
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

	const handleQuery = useCallback(
		async (overrideQuery, overrideModelChoice) => {
			if (!query.trim() && !overrideQuery) {
				toast.warning("You can't query an empty question.")

				setLoading(true)
				setInQueueQuery(overrideQuery || query)

				const data = await Query(
					overrideQuery || query,
					overrideModelChoice === "thinking" ||
						modelChoice === "thinking"
				)
				console.info(data)

				setInQueueQuery(null)
				setQuery("")

				if (data) {
					setHistory((prev) => [
						...prev,
						{
							query: overrideQuery || query,
							answer: data.answer,
							model: overrideModelChoice || modelChoice,
						},
					])
				}

				setLoading(false)
			}
		},
		[query, setLoading, setInQueueQuery, setHistory, setQuery, modelChoice]
	)

	return (
		<div className="relative bg-background w-screen h-screen flex flex-col">
			{/* Chat Window */}
			<div className="flex-1 w-full max-w-5xl mx-auto px-4 py-6 pb-20 overflow-y-auto hide-scrollbar">
				{/* Past Queries */}
				{history.map((row, i) => (
					<div key={i} className="mb-30">
						<UserPrompt
							query={row.query}
							handleEditQuery={handleEditQuery}
						/>
						<LlmResponse
							answer={row.answer}
							handleThinkMore={() => {
								handleQuery(row.query, "thinking")
							}}
							showThinkMoreOption={row.model === "thinking"}
						/>
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

				<div ref={chatEndRef} className="mb-[20vh]" />
			</div>

			{/* Input Box For New Queries */}
			<div className="absolute bottom-10 w-full">
				<QueryInput
					query={query}
					setQuery={setQuery}
					modelChoice={modelChoice}
					setModelChoice={setModelChoice}
					loading={loading}
					handleQuery={handleQuery}
				/>
			</div>
		</div>
	)
}
