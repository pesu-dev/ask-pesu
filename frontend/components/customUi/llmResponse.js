import { Bot, Clipboard, BrainCircuit } from "lucide-react"
import { motion } from "motion/react"
import ReactMarkdown from "react-markdown"
import { Button } from "../ui/button"
import {
	Tooltip,
	TooltipContent,
	TooltipProvider,
	TooltipTrigger,
} from "../ui/tooltip"

export default function LlmResponse({
	answer,
	query,
	onThinkingMode,
	isThinkingAvailable,
	thinkingNextAvailable,
	getTimeRemaining,
	quotaLoading,
}) {
	const timeRemaining = getTimeRemaining(thinkingNextAvailable)
	const isDisabled = quotaLoading || !isThinkingAvailable

	const ThinkingButton = () => (
		<Button
			className="rounded-2xl text-white hover:text-white"
			variant={"outline"}
			onClick={() => onThinkingMode(query)}
			disabled={isDisabled}
		>
			<BrainCircuit className="mr-2 h-4 w-4" />
			Think longer for a better answer
		</Button>
	)

	return (
		<motion.div
			initial={{ opacity: 0, x: -30 }}
			animate={{ opacity: 1, x: 0 }}
			className="flex justify-start mt-3 gap-4"
		>
			<Bot className="w-max h-max rounded-full border p-2 size-10 min-w-10 min-h-10" />
			<div className="flex flex-col flex-nowrap gap-4">
				<div className="bg-accent/30 px-4 py-3 rounded-4xl shadow-2xl text-foreground text-base leading-relaxed prose dark:prose-invert wrap-anywhere">
					<ReactMarkdown>{answer}</ReactMarkdown>
					<div className="flex gap-3 mt-4">
						<Button
							className="rounded-2xl text-accent hover:text-accent"
							variant={"outline"}
							onClick={() => {
								navigator.clipboard.writeText(answer)
							}}
						>
							<Clipboard />
						</Button>

						{isDisabled && timeRemaining ? (
							<TooltipProvider>
								<Tooltip>
									<TooltipTrigger asChild>
										<div>
											<ThinkingButton />
										</div>
									</TooltipTrigger>
									<TooltipContent>
										<p>
											Thinking mode is currently
											unavailable due to usage limits and
											will be back in {timeRemaining}
										</p>
									</TooltipContent>
								</Tooltip>
							</TooltipProvider>
						) : (
							<ThinkingButton />
						)}
					</div>
				</div>
			</div>
		</motion.div>
	)
}
