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
	const [loading, setLoading] = useState(false)
	const [modelChoice, setModelChoice] = useState("thinking")
	const [isFirstQuery, setIsFirstQuery] = useState(true)

	const chatEndRef = useRef(null)

	const {
		refreshQuota,
		getTimeRemaining,
		isThinkingAvailable,
		thinkingNextAvailable,
	} = useQuota()

	const serviceStatus = useServiceStatus()

	useEffect(() => {
		chatEndRef.current?.scrollIntoView({
			behavior: loading ? "auto" : "smooth",
		})
	}, [history, loading])

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
		serviceStatus.message,
	])

	const handleEditQuery = useCallback((editedQuery) => {
		setQuery(editedQuery)
	}, [])

	const runStreamedQuery = useCallback(
		async (queryText, thinkingFlag) => {
			setLoading(true)

			const rowId = crypto.randomUUID()

			setHistory((prev) => [
				...prev,
				{
					id: rowId,
					query: queryText,
					answer: "",
					steps: "",
					isStreaming: true,
					hasReceivedBytes: false,
					isDone: false,
					wasThinkingMode: thinkingFlag,
				},
			])

			const updateRow = (updater) => {
				setHistory((prev) =>
					prev.map((row) => (row.id === rowId ? updater(row) : row))
				)
			}

			const result = await Query(queryText, thinkingFlag, history, {
				onFirstByte: () => {
					updateRow((row) => ({ ...row, hasReceivedBytes: true }))
				},
				onToken: (token) => {
					updateRow((row) => ({
						...row,
						hasReceivedBytes: true,
						answer: (row.answer || "") + token,
					}))

					requestAnimationFrame(() => {
						chatEndRef.current?.scrollIntoView({ behavior: "auto" })
					})
				},
				onStep: (step) => {
					updateRow((row) => ({
						...row,
						hasReceivedBytes: true,
						steps: (row.steps || "") + step,
					}))
				},
				onDone: () => {
					updateRow((row) => ({
						...row,
						isStreaming: false,
						isDone: true,
					}))
					setLoading(false)
				},
			})

			if (!result?.status) {
				toast.error(result?.message || "Request failed")
				updateRow((row) => ({
					...row,
					isStreaming: false,
					isDone: true,
				}))
				if (result?.httpStatus === 429) {
					refreshQuota()
					serviceStatus.refreshStatus?.()
				}
				setLoading(false)
			}
		},
		[history, refreshQuota, serviceStatus]
	)

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

			await runStreamedQuery(queryText, true)
		},
		[
			isThinkingAvailable,
			thinkingNextAvailable,
			getTimeRemaining,
			runStreamedQuery,
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

		// Thinking mode by default
		const useThinkingMode =
			modelChoice === "thinking" && isThinkingAvailable

		await runStreamedQuery(currentQuery, useThinkingMode)
	}, [
		query,
		serviceStatus.isAvailable,
		modelChoice,
		isThinkingAvailable,
		runStreamedQuery,
	])

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
		<div className="bg-background min-h-screen flex flex-col">
			<div
				className={`w-full max-w-5xl mx-auto px-4 py-6 transition-opacity duration-500 ${
					isFirstQuery
						? "opacity-0 pointer-events-none"
						: "opacity-100"
				}`}
			>
				{history.map((row, i) => (
					<div key={i} className="mb-6">
						<UserPrompt
							query={row.query}
							handleEditQuery={handleEditQuery}
						/>

						{row.isStreaming && !row.hasReceivedBytes && (
							<div className="flex justify-start mt-3">
								<PendingResponse />
							</div>
						)}

						<LlmResponse
							answer={row.answer}
							steps={row.steps}
							isStreaming={row.isStreaming}
							hasReceivedBytes={row.hasReceivedBytes}
							handleThinkMode={() =>
								handleThinkingMode(row.query)
							}
							showThinkMoreOption={Boolean(
								row.isDone && isThinkingAvailable
							)}
							wasThinkingMode={row.wasThinkingMode}
						/>
					</div>
				))}
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
