import { useState, useEffect, useCallback } from "react"

export default function useQuota() {
	const [quotaStatus, setQuotaStatus] = useState({
		thinking: { available: true, next_available: null },
		primary: { available: true, next_available: null },
	})
	const [loading, setLoading] = useState(true)

	const fetchQuota = useCallback(async () => {
		try {
			const API_URL = process.env.NEXT_PUBLIC_DEV_API_URL || ""
			const response = await fetch(`${API_URL}/quota`)
			if (response.ok) {
				const data = await response.json()
				if (data.status && data.quota) {
					setQuotaStatus(data.quota)
				}
			} else {
				console.error("Failed to fetch quota:", response.status)
			}
		} catch (error) {
			console.error("Error fetching quota:", error)
		} finally {
			setLoading(false)
		}
	}, [])

	const refreshQuota = useCallback(() => {
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
		fetchQuota()

		// Set up interval to refresh quota every 5 minutes
		const interval = setInterval(fetchQuota, 5 * 60 * 1000)

		return () => clearInterval(interval)
	}, [fetchQuota])

	return {
		quotaStatus,
		loading,
		refreshQuota,
		getTimeRemaining,
		isThinkingAvailable: quotaStatus.thinking?.available || false,
		thinkingNextAvailable: quotaStatus.thinking?.next_available,
	}
}
