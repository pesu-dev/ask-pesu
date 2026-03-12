import { motion, AnimatePresence } from "motion/react"
import { Bot } from "lucide-react"
import { useState, useEffect } from "react"

const statuses = ["Analyzing the question...", "Thinking...", "Almost there..."]

export default function PendingResponse() {
	const [statusIndex, setStatusIndex] = useState(0)

	useEffect(() => {
		const interval = setInterval(() => {
			setStatusIndex((prev) => (prev + 1) % statuses.length)
		}, 2500)
		return () => clearInterval(interval)
	}, [])

	return (
		<motion.div
			initial={{ opacity: 0, x: -30 }}
			animate={{ opacity: 1, x: 0 }}
			className="flex justify-start mt-3 gap-4"
		>
			<Bot className="rounded-full p-2 hidden md:block min-w-10 min-h-10 ring-2 ring-accent/40 text-accent" />
			<div className="bg-muted px-4 py-3 rounded-2xl text-neutral-500 shadow flex items-center gap-2 min-w-[200px]">
				<AnimatePresence mode="wait">
					<motion.span
						key={statusIndex}
						initial={{ opacity: 0, y: 8 }}
						animate={{ opacity: 1, y: 0 }}
						exit={{ opacity: 0, y: -8 }}
						transition={{ duration: 0.3 }}
						className="italic text-sm"
					>
						{statuses[statusIndex]}
					</motion.span>
				</AnimatePresence>
			</div>
		</motion.div>
	)
}
