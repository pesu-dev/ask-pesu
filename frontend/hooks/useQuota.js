import { useState, useEffect, useCallback } from "react"

export default function useQuota() {
	const [quotaStatus, setQuotaStatus] = useState({
		thinking: { available: true, next_available: null },
		primary: { available: true, next_available: null },
	})
	const [loading, setLoading] = useState(true)

	const BASE =
		process.env.NEXT_PUBLIC_DEV_API_URL?.replace(/\/ask$/, "") || ""

	const fetchQuota = useCallback(async () => {
		try {
			console.log("🔄 Fetching quota from:", `${BASE}/quota`)
			const response = await fetch(`${BASE}/quota`)

			if (response.ok) {
				const data = await response.json()
				console.log("📊 Raw quota response:", data)

				if (data.status && data.quota) {
					setQuotaStatus(data.quota)
					console.log("✅ Quota status updated:", data.quota)
					console.log(
						"🧠 Thinking available:",
						data.quota.thinking?.available
					)
					console.log(
						"⚡ Primary available:",
						data.quota.primary?.available
					)

					if (
						!data.quota.thinking?.available &&
						data.quota.thinking?.next_available
					) {
						const timeRemaining = getTimeRemaining(
							data.quota.thinking.next_available
						)
						console.log(
							"⏰ Thinking mode will be available in:",
							timeRemaining
						)
					}
				}
			} else {
				console.error(
					"❌ Failed to fetch quota:",
					response.status,
					response.statusText
				)
			}
		} catch (error) {
			console.error("🚨 Error fetching quota:", error)
		} finally {
			setLoading(false)
		}
	}, [BASE])

	const refreshQuota = useCallback(() => {
		console.log("🔁 Manually refreshing quota...")
		fetchQuota()
	}, [fetchQuota])

	const getTimeRemaining = useCallback((nextAvailable) => {
		if (!nextAvailable) return null

		const now = new Date()
		const available = new Date(nextAvailable)
		const diffMs = available - now

		if (diffMs <= 0) return null

		const hours = Math.floor(diffMs / (1000 * 60 * 60))
		const minutes = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60))

		if (hours > 0) {
			return `${hours} hour${hours > 1 ? "s" : ""} ${
				minutes > 0
					? `and ${minutes} minute${minutes > 1 ? "s" : ""}`
					: ""
			}`
		}
		return `${minutes} minute${minutes > 1 ? "s" : ""}`
	}, [])

	useEffect(() => {
		console.log("🚀 useQuota hook initialized")
		fetchQuota()

		// Set up interval to refresh quota every 5 minutes
		const interval = setInterval(() => {
			console.log("⏰ Auto-refreshing quota (5min interval)")
			fetchQuota()
		}, 5 * 60 * 1000)

		return () => {
			console.log("🛑 Cleaning up quota interval")
			clearInterval(interval)
		}
	}, [fetchQuota])

	// Log whenever quota status changes
	useEffect(() => {
		console.log("📈 Current quota status:", quotaStatus)
	}, [quotaStatus])

	return {
		quotaStatus,
		loading,
		refreshQuota,
		getTimeRemaining,
		isThinkingAvailable: quotaStatus.thinking?.available || false,
		thinkingNextAvailable: quotaStatus.thinking?.next_available,
	}
}
