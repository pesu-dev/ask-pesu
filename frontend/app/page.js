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
import Sidebar from "@/components/customUi/sideBar"

export default function Home() {
	const [query, setQuery] = useState("")
	const [sessions, setSessions] = useState([])
	const [currentSessionId, setCurrentSessionId] = useState(null)
	const [loading, setLoading] = useState(false)
	const [modelChoice, setModelChoice] = useState("thinking")
	const [hasLoaded, setHasLoaded] = useState(false)
	const [isSidebarExpanded, setIsSidebarExpanded] = useState(false)

	const currentSession = sessions.find((s) => s.id === currentSessionId)
	const history = currentSession?.history || []
	const isFirstQuery = history.length === 0

	const chatEndRef = useRef(null)

	useEffect(() => {
		try {
			const savedSessions = localStorage.getItem("chatSessions")
			if (savedSessions) {
				const parsedSessions = JSON.parse(savedSessions)
				if (
					Array.isArray(parsedSessions) &&
					parsedSessions.length > 0
				) {
					setSessions(parsedSessions)
					setCurrentSessionId(parsedSessions[0].id)
				}
			}
		} catch (error) {
			console.error(
				"Failed to parse chat history from localStorage",
				error
			)
			toast.error("Could not load your chat history.")
		} finally {
			setHasLoaded(true)
		}
	}, [])

	useEffect(() => {
		if (!hasLoaded) {
			return
		}

		try {
			const sessionsToSave = sessions.map((session) => ({
				...session,
				history: session.history.map(
					({ isStreaming, hasReceivedBytes, ...rest }) => rest
				),
			}))
			localStorage.setItem("chatSessions", JSON.stringify(sessionsToSave))
		} catch (error) {
			console.error("Failed to save chat history to localStorage", error)
			toast.error("Could not save your chat history.")
		}
	}, [sessions, hasLoaded])

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

	const handleNewChat = useCallback(() => {
		setCurrentSessionId(null)
	}, [])

	const handleSelectChat = useCallback((id) => {
		setCurrentSessionId(id)
	}, [])

	const handleDeleteChat = useCallback(
		(id) => {
			setSessions((prev) => {
				const filtered = prev.filter((s) => s.id !== id)
				if (currentSessionId === id) {
					setCurrentSessionId(
						filtered.length > 0 ? filtered[0].id : null
					)
				}
				return filtered
			})
		},
		[currentSessionId]
	)

	const handleEditQuery = useCallback((editedQuery) => {
		setQuery(editedQuery)
	}, [])

	const rewriteChatTitle = useCallback(async (sessionId, queryText) => {
		try {
			const response = await fetch(`/rewriteQuery`, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({
					query: queryText,
					thinking: false,
					history: [],
				}),
			})

			if (!response.ok) throw new Error("API response not ok")

			const data = await response.json()
			if (data && data.query) {
				setSessions((prev) =>
					prev.map((s) =>
						s.id === sessionId
							? {
									...s,
									title: data.query
										.replace(/["*]/g, "")
										.trim(),
									isGeneratingTitle: false,
								}
							: s
					)
				)
			} else {
				throw new Error("No query string in response")
			}
		} catch (error) {
			console.error("Failed to rewrite chat title:", error)
			setSessions((prev) =>
				prev.map((s) =>
					s.id === sessionId
						? {
								...s,
								title: "New Conversation",
								isGeneratingTitle: false,
							}
						: s
				)
			)
		}
	}, [])

	const runStreamedQuery = useCallback(
		async (queryText, thinkingFlag) => {
			setLoading(true)

			const rowId = crypto.randomUUID()
			let targetSessionId = currentSessionId
			let isNewSession = false

			if (!targetSessionId) {
				targetSessionId = crypto.randomUUID()
				setCurrentSessionId(targetSessionId)
				isNewSession = true

				setSessions((prev) => [
					{
						id: targetSessionId,
						title: "",
						isGeneratingTitle: true,
						history: [],
					},
					...prev,
				])
			}

			if (isNewSession) {
				rewriteChatTitle(targetSessionId, queryText)
			}

			const newRow = {
				id: rowId,
				query: queryText,
				answer: "",
				steps: "",
				isStreaming: true,
				hasReceivedBytes: false,
				isDone: false,
				wasThinkingMode: thinkingFlag,
			}

			const updateSessionHistory = (updater) => {
				setSessions((prev) =>
					prev.map((session) => {
						if (session.id !== targetSessionId) return session

						const rowExists = session.history.some(
							(r) => r.id === rowId
						)
						const newHistory = rowExists
							? session.history.map((row) =>
									row.id === rowId ? updater(row) : row
								)
							: [...session.history, updater(newRow)]

						return { ...session, history: newHistory }
					})
				)
			}

			updateSessionHistory((r) => r)

			const activeHistory =
				sessions.find((s) => s.id === targetSessionId)?.history || []

			const result = await Query(queryText, thinkingFlag, activeHistory, {
				onFirstByte: () => {
					updateSessionHistory((row) => ({
						...row,
						hasReceivedBytes: true,
					}))
				},
				onToken: (token) => {
					updateSessionHistory((row) => ({
						...row,
						hasReceivedBytes: true,
						answer: (row.answer || "") + token,
					}))

					requestAnimationFrame(() => {
						chatEndRef.current?.scrollIntoView({ behavior: "auto" })
					})
				},
				onStep: (step) => {
					updateSessionHistory((row) => ({
						...row,
						hasReceivedBytes: true,
						steps: (row.steps || "") + step,
					}))
				},
				onDone: () => {
					updateSessionHistory((row) => ({
						...row,
						isStreaming: false,
						isDone: true,
					}))
					setLoading(false)
				},
			})

			if (!result?.status) {
				toast.error(result?.message || "Request failed")
				updateSessionHistory((row) => ({
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
		[
			currentSessionId,
			sessions,
			refreshQuota,
			serviceStatus,
			rewriteChatTitle,
		]
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

		const currentQuery = query
		setQuery("")

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
		<div className="flex h-screen bg-background overflow-hidden">
			<Sidebar
				chatSessions={sessions}
				currentSessionId={currentSessionId}
				onSelectChat={handleSelectChat}
				onNewChat={handleNewChat}
				onDeleteChat={handleDeleteChat}
				isSidebarExpanded={isSidebarExpanded}
				setIsSidebarExpanded={setIsSidebarExpanded}
			/>

			<div className="flex-1 relative flex flex-col overflow-y-auto">
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
					<div className="absolute top-0 left-0 right-0 z-10 w-full bg-destructive/10 border-b border-destructive/20 px-4 py-3">
						<p className="text-center text-sm text-destructive font-medium">
							⚠️ {serviceStatus.message}
						</p>
					</div>
				)}

				<div
					className={`fixed ${isSidebarExpanded ? "left-96" : "left-64"} right-0 px-4 flex flex-col items-center transition-all duration-300 ease-in-out z-10`}
					style={{
						top: "50%",
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
		</div>
	)
}
