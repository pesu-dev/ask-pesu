import {
	ArrowBigRight,
	ArrowBigRightDash,
	ArrowRight,
	ArrowRightCircle,
	ArrowRightToLine,
	ArrowUp,
	ArrowUpRight,
	Send,
	SendHorizonal,
} from "lucide-react"
import { Button } from "../ui/button"

export default function QueryInput({ query, setQuery, loading, handleQuery }) {
	return (
		<div className="flex flex-nowrap gap-5 w-[90vw] max-w-4xl mx-auto pl-10 pr-4 py-2 bg-accent rounded-full border-4">
			<input
				disabled={loading}
				className="rounded-r-none w-full outline-none border-none text-lg"
				placeholder="Ask me anything..."
				value={query}
				onChange={(e) => setQuery(e.target.value)}
				onKeyDown={(e) => {
					if (e.key === "Enter" && !loading) {
						handleQuery()
					}
				}}
			/>
			<Button
				disabled={loading}
				className="rounded-l-none rounded-full w-12 h-10"
				onClick={handleQuery}
			>
				<SendHorizonal className="size-4" />
			</Button>
		</div>
	)
}
