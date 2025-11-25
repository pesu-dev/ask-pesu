import { Bot, Clipboard } from "lucide-react"
import { motion } from "motion/react"
import ReactMarkdown from "react-markdown"
import { Button } from "../ui/button"

export default function LlmResponse({
	answer,
	handleThinkMore,
	showThinkMoreOption = false,
}) {
	return (
		<motion.div
			initial={{ opacity: 0, x: -30 }}
			animate={{ opacity: 1, x: 0 }}
			className="flex justify-start mt-3 gap-4"
		>
			<Bot className="rounded-full p-2 hidden md:block min-w-10 min-h-10 ring-2 ring-accent/40 text-accent" />
			<div className="flex flex-col flex-nowrap gap-4">
				<div className="bg-card px-4 py-3 rounded-2xl text-card-foreground text-base leading-relaxed prose dark:prose-invert wrap-anywhere">
					<ReactMarkdown>{answer}</ReactMarkdown>
					<Button
						className="rounded-2xl text-card-foreground hover:text-card-foreground/50 cursor-pointer"
						variant={"outline"}
						onClick={() => {
							navigator.clipboard.writeText(answer)
						}}
					>
						<Clipboard />
					</Button>
				</div>
				{showThinkMoreOption ? (
					<div className="flex gap-4">
						<Button
							className="rounded-4xl"
							variant={"outline"}
							onClick={handleThinkMore}
						>
							{"Think longer for a better answer"}
						</Button>
					</div>
				) : null}
			</div>
		</motion.div>
	)
}
