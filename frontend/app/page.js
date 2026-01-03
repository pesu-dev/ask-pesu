"use client"

import { useState, useEffect, useRef, useCallback } from "react"
import UserPrompt from "@/components/customUi/userPrompt"
import QueryInput from "@/components/customUi/queryInput"
import LlmResponse from "@/components/customUi/llmResponse"
import Query from "./utils/query"
import { toast } from "sonner"
import useQuota from "@/hooks/useQuota"
import ThinkingIndicator from "@/components/customUi/thinkinganimation"

export default function Home() {
	const [query, setQuery] = useState("")
	const [history, setHistory] = useState([])
	const [inQueueQuery, setInQueueQuery] = useState("")
	const [loading, setLoading] = useState(false)
	const [modelChoice, setModelChoice] = useState("primary")
	const chatEndRef = useRef(null)

	// useEffect(() => {
	// 	console.log("API URL:", process.env.NEXT_PUBLIC_DEV_API_URL)
	// }, [])

	const {
		quotaStatus,
		loading: quotaLoading,
		refreshQuota,
		getTimeRemaining,
		isThinkingAvailable,
		thinkingNextAvailable,
	} = useQuota()

	// Auto-scroll to bottom on new message
	useEffect(() => {
		chatEndRef.current?.scrollIntoView({ behavior: "smooth" })
	}, [history, inQueueQuery, chatEndRef])

	const handleEditQuery = useCallback((query) => {
		setQuery(query)
	}, [])

	const handleThinkingMode = useCallback(
		async (queryText) => {
			if (!isThinkingAvailable) {
				const timeRemaining = getTimeRemaining(thinkingNextAvailable)
				toast.warning(
					`Thinking mode is currently unavailable due to usage limits${
						timeRemaining
							? ` and will be back in ${timeRemaining}`
							: ""
					}.`
				)
				return
			}

			setLoading(true)
			setInQueueQuery(queryText)

			const data = await Query(queryText, true, history)
			console.info(data)

			setInQueueQuery(null)

			if (data) {
				setHistory((prev) => [
					...prev,
					{
						query: queryText,
						answer: data.answer,
					},
				])
			} else {
				// If query failed, refresh quota to check if thinking mode went down
				refreshQuota()
			}

			setLoading(false)
		},
		[
			isThinkingAvailable,
			thinkingNextAvailable,
			getTimeRemaining,
			refreshQuota,
			history,
		]
	)
	console.log("Rendering Home component")

	const handleQuery = useCallback(async () => {
		if (!query.trim()) {
			toast.warning("You can't query an empty question.")
			return
		}

		setLoading(true)
		setInQueueQuery(query)

		const data = await Query(query, false, history)
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
	}, [query, setLoading, setInQueueQuery, setHistory, setQuery, history])

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
						<LlmResponse
							answer={row.answer}
							query={row.query}
							onThinkingMode={handleThinkingMode}
							isThinkingAvailable={isThinkingAvailable}
							thinkingNextAvailable={thinkingNextAvailable}
							getTimeRemaining={getTimeRemaining}
							handleThinkMode={() => handleThinkingMode(row.query)}
							showThinkMoreOption={isThinkingAvailable}
							quotaLoading={quotaLoading}
						/>
					</div>
				))}

				{/* Pending Query */}
				{inQueueQuery && (
					<div className="mb-6">
						<UserPrompt query={inQueueQuery} />

						<div className="flex justify-start mt-3">
							<ThinkingIndicator />
						</div>
					</div>
				)}

				<div ref={chatEndRef} className="mb-[20vh]" />
			</div>

			{/* Input Box For New Queries */}
			<div className="absolute bottom-10 w-full ">
				<QueryInput
					query={query}
					setQuery={setQuery}
					loading={loading}
					handleQuery={handleQuery}
					modelChoice={modelChoice}
					setModelChoice={setModelChoice}
				/>
			</div>
		</div>
	)
}
