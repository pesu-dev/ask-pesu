import { useState, useEffect } from "react"
import useSWR from "swr"

const fetcher = (...args) => {
	console.log("🔍 Fetching quota status at:", new Date().toLocaleTimeString())
	fetch(...args).then((res) => res.json())
}

export default function useServiceStatus() {
	const API_URL = process.env.NEXT_PUBLIC_DEV_API_URL
	const url = `${API_URL}/quota`
	const { data, error } = useSWR(url, fetcher)

	const [serviceStatus, setServiceStatus] = useState({
		isAvailable: true,
		message: "",
		nextAvailableTime: null,
		isPrimaryDown: false,
		isThinkingDown: false,
	})

	useEffect(() => {
		console.log(
			"📊 Quota data updated at:",
			new Date().toLocaleTimeString(),
			data
		)

		if (!data) return

		const primaryAvailable = data?.quota?.primary?.available ?? true
		const thinkingAvailable = data?.quota?.thinking?.available ?? true
		const primaryNextAvailable = data?.quota?.primary?.next_available
		const thinkingNextAvailable = data?.quota?.thinking?.next_available

		// If primary is down, service is unavailable
		if (!primaryAvailable) {
			const nextTime = primaryNextAvailable
				? new Date(primaryNextAvailable)
				: null
			const timeRemaining = getTimeRemaining(nextTime)

			setServiceStatus({
				isAvailable: false,
				message: "Service temporarily unavailable due to usage limits",
				nextAvailableTime: nextTime,
				isPrimaryDown: true,
				isThinkingDown: !thinkingAvailable,
			})
		} else {
			setServiceStatus({
				isAvailable: true,
				message: "",
				nextAvailableTime: null,
				isPrimaryDown: false,
				isThinkingDown: !thinkingAvailable,
			})
		}
	}, [data])

	const getTimeRemaining = (nextAvailableTime) => {
		if (!nextAvailableTime) return null

		const now = new Date()
		const diff = new Date(nextAvailableTime) - now

		if (diff <= 0) return null

		const hours = Math.floor(diff / (1000 * 60 * 60))
		const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60))

		if (hours > 0) {
			return `${hours} hour${hours > 1 ? "s" : ""} ${minutes} minute${
				minutes !== 1 ? "s" : ""
			}`
		}
		return `${minutes} minute${minutes !== 1 ? "s" : ""}`
	}

	return serviceStatus
}
