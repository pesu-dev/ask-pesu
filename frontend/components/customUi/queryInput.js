import { Brain, BrainCircuit, Lightbulb, SendHorizonal } from "lucide-react"
import { Button } from "../ui/button"

export default function QueryInput({
	thinkingMode,
	setThinkingMode,
	query,
	setQuery,
	loading,
	handleQuery,
}) {
	return (
		<div className="w-[90vw] max-w-4xl mx-auto flex flex-col flex-nowrap gap-4">
			<div className="flex flex-nowrap gap-5 px-4 py-2 bg-accent rounded-full border-4">
				<Button
					title={"Toggle Thinking Model"}
					className={`rounded-full w-max m-auto transition-all ${
						thinkingMode
							? "bg-green-300/50 text-white ring-2 ring-green-300"
							: "hover:ring-2 ring-green-300"
					}`}
					variant={thinkingMode ? "" : "outline"}
					onClick={() => {
						setThinkingMode((prev) => !prev)
					}}
				>
					<Lightbulb />
				</Button>
				<textarea
					rows={1}
					style={{
						minHeight: "40px",
						maxHeight: "120px", // 5 lines
						resize: "none",
						lineHeight: "1.9",
						overflow: query.trim() ? "auto" : "hidden",
					}}
					onInput={(e) => {
						e.target.style.height = "auto"
						e.target.style.height =
							Math.min(e.target.scrollHeight, 120) + "px"
					}}
					cols={100}
					disabled={loading}
					className="w-full h-full outline-none m-auto text-lg placeholder:text-left"
					placeholder="Ask me anything about PESU..."
					value={query}
					onChange={(e) => setQuery(e.target.value)}
					onKeyDown={(e) => {
						if (e.key === "Enter" && !e.shiftKey && !loading) {
							handleQuery()
						}
					}}
				/>
				<Button
					disabled={loading}
					className="rounded-full w-12 h-10"
					onClick={handleQuery}
				>
					<SendHorizonal className="size-4" />
				</Button>
			</div>
		</div>
	)
}
