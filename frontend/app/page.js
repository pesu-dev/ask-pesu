"use client"

import { useState, useEffect, useRef, useCallback } from "react"
import UserPrompt from "@/components/customUi/userPrompt"
import QueryInput from "@/components/customUi/queryInput"
import LlmResponse from "@/components/customUi/llmResponse"
import Query from "./utils/query"
import { toast } from "sonner"
import useQuota from "@/hooks/useQuota"
import PendingResponse from "@/components/customUi/thinkinganimation"
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

	useEffect(() => {
		chatEndRef.current?.scrollIntoView({ behavior: "smooth" })
	}, [history, inQueueQuery, chatEndRef])

	useEffect(() => {
		if (!serviceStatus.isAvailable && serviceStatus.message) {
			const timeRemaining = getTimeRemaining(
				serviceStatus.nextAvailableTime
			)
			toast.error(
				`Quota exhausted. ${
					timeRemaining
						? `Will be back in ${timeRemaining}.`
						: "Please try again later."
				}`
			)
		}
	}, [
		serviceStatus.isAvailable,
		serviceStatus.nextAvailableTime,
		getTimeRemaining,
	])

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
					serviceStatus.refreshStatus?.()
				}
				setInQueueQuery(null)
				setLoading(false)
				return
			}

			setInQueueQuery(null)

			if (data) {
				setHistory((prev) => [
					...prev,
					{
						query: queryText,
						answer: data.answer,
						steps: data.steps || null,
					},
				])
			} else {
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
		toast.error("Service temporarily unavailable")
		return
	}

	setIsFirstQuery(false)

	const currentQuery = query
	setQuery("")
	setInQueueQuery(null)

	const messageIndex = history.length

	// Insert empty message
	setHistory(prev => [
		...prev,
		{
			query: currentQuery,
			answer: "",
			steps: "",
		},
	])

	setLoading(true)

	await Query(
		currentQuery,
		isThinkingAvailable,
		history,
		{
			onToken: (token) => {
				setHistory(prev => {
					const updated = [...prev]
					updated[messageIndex].answer += token
					return updated
				})
			},

			onStep: (step) => {
				setHistory(prev => {
					const updated = [...prev]
					updated[messageIndex].steps =
						(updated[messageIndex].steps || "") + step
					return updated
				})
			},

			onDone: () => {
				setLoading(false)
			},
		}
	)
}, [query, history, serviceStatus, isThinkingAvailable])

	const getDisabledMessage = useCallback(() => {
		if (!serviceStatus.isAvailable) {
			const timeRemaining = getTimeRemaining(
				serviceStatus.nextAvailableTime
			)
			return `Quota exhausted. Will be back ${
				timeRemaining ? `in ${timeRemaining}` : "soon"
			}.`
		}
		return null
	}, [serviceStatus, getTimeRemaining])

	return (
		<div className="relative bg-background w-screen h-screen flex flex-col">
			<div
				className={`flex-1 w-full max-w-5xl mx-auto px-4 py-6 overflow-y-auto hide-scrollbar transition-opacity duration-500 ${
					isFirstQuery
						? "opacity-0 pointer-events-none"
						: "opacity-100"
				}`}
			>
				{" "}
				{history.map((row, i) => (
					<div key={i} className="mb-6">
						<UserPrompt
							query={row.query}
							handleEditQuery={handleEditQuery}
						/>
						<LlmResponse
							answer={row.answer}
							steps={row.steps}
							handleThinkMode={() =>
								handleThinkingMode(row.query)
							}
							showThinkMoreOption={isThinkingAvailable}
						/>
					</div>
				))}
				{/* {inQueueQuery && (
					<div className="mb-6">
						<UserPrompt query={inQueueQuery} />
						<div className="flex justify-start mt-3">
							<PendingResponse />
						</div>
					</div>
				)} */}
				<div ref={chatEndRef} className="mb-[20vh]" />
			</div>

			{!serviceStatus.isAvailable && (
				<div className="w-full bg-destructive/10 border-b border-destructive/20 px-4 py-3">
					<p className="text-center text-sm text-destructive font-medium">
						⚠️ {serviceStatus.message}
					</p>
				</div>
			)}

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
					disabled={!serviceStatus.isAvailable}
					disabledMessage={getDisabledMessage()}
				/>
			</div>
		</div>
	)
}
