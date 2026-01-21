import { useState, useEffect } from "react"
import useSWR from "swr"

const fetcher = (...args) => {
	console.log("🔍 Fetching quota status at:", new Date().toLocaleTimeString())
	return fetch(...args).then((res) => res.json())
}

export default function useServiceStatus() {
	const url = `/quota`
	const { data, error, mutate } = useSWR(url, fetcher, {
		revalidateOnFocus: true,
		revalidateOnMount: true,
		dedupingInterval: 5000,
	})

	const [serviceStatus, setServiceStatus] = useState({
		isAvailable: true,
		message: "",
		nextAvailableTime: null,
		isPrimaryDown: false,
		isThinkingDown: false,
	})

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
				//message: "Service temporarily unavailable due to usage limits",
				message: `Service temporarily unavailable due to usage limits${
					timeRemaining ? `. Will be back in ${timeRemaining}` : ""
				}`,
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

	return {
		...serviceStatus,
		refreshStatus: mutate,
	}
}
