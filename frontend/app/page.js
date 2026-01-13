"use client"

import { useState, useEffect, useRef, useCallback } from "react"
import UserPrompt from "@/components/customUi/userPrompt"
import QueryInput from "@/components/customUi/queryInput"
import LlmResponse from "@/components/customUi/llmResponse"
import Query from "./utils/query"
import { toast } from "sonner"
import useQuota from "@/hooks/useQuota"
import ThinkingIndicator from "@/components/customUi/thinkinganimation"
import useServiceStatus from "@/hooks/useAvail"

export default function Home() {
	const [query, setQuery] = useState("")
	const [history, setHistory] = useState([])
	const [inQueueQuery, setInQueueQuery] = useState("")
	const [loading, setLoading] = useState(false)
	const [modelChoice, setModelChoice] = useState("primary")
	const chatEndRef = useRef(null)
	const [isFirstQuery, setIsFirstQuery] = useState(true)

	const {
		quotaStatus,
		loading: quotaLoading,
		refreshQuota,
		getTimeRemaining,
		isThinkingAvailable,
		thinkingNextAvailable,
	} = useQuota()

	const serviceStatus = useServiceStatus()

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

			if (!data || !data.status) {
				toast.error(data?.message || "Request failed")
				if (data?.httpStatus === 429) {
					refreshQuota()
				}
				setInQueueQuery(null)
				setLoading(false)
				return
			}

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

	const handleQuery = useCallback(async () => {
		if (!query.trim()) {
			toast.warning("You can't query an empty question.")
			return
		}

		if (!serviceStatus.isAvailable) {
			const timeRemaining = getTimeRemaining(
				serviceStatus.nextAvailableTime
			)
			toast.error("Service temporarily unavailable")
			return
		}

		setIsFirstQuery(false)
		setLoading(true)
		setInQueueQuery(query)

		const data = await Query(query, false, history)
		console.info(data)

		setInQueueQuery(null)
		setQuery("")

		if (!data || !data.status) {
			toast.error(data?.message || "Request failed")
			// Refresh quota in case it was a 429 error
			if (data?.httpStatus === 429) {
				refreshQuota()
			}
			setLoading(false)
			return
		}

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
	}, [
		query,
		setLoading,
		setInQueueQuery,
		setHistory,
		setQuery,
		history,
		serviceStatus,
	])

	return (
		<div className="relative bg-background w-screen h-screen flex flex-col">
			{/* Chat Window */}
			<div
				className={`flex-1 w-full max-w-5xl mx-auto px-4 py-6 overflow-y-auto hide-scrollbar transition-opacity duration-500 ${
					isFirstQuery
						? "opacity-0 pointer-events-none"
						: "opacity-100"
				}`}
			>
				{" "}
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
							handleThinkMode={() =>
								handleThinkingMode(row.query)
							}
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

			{/* Service Status Banner */}
			{!serviceStatus.isAvailable && (
				<div className="w-full bg-destructive/10 border-b border-destructive/20 px-4 py-3">
					<p className="text-center text-sm text-destructive font-medium">
						⚠️ {serviceStatus.message}
					</p>
				</div>
			)}

			{/* Input Box For New Queries */}
			<div
				className="fixed left-0 right-0 top-1/2 transition-transform duration-700 ease-in-out"
				style={{
					transform: isFirstQuery
						? "translateY(-50%)"
						: "translateY(calc(50vh - 120px))",
				}}
			>
				{isFirstQuery && (
					<h1 className="text-6xl text-blue-600 font-bold text-center mb-8 transition-opacity duration-700">
						AskPESU
					</h1>
				)}
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
