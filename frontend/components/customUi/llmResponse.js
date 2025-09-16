import { Bot, Clipboard } from "lucide-react"
import { motion } from "motion/react"
import ReactMarkdown from "react-markdown"
import { Button } from "../ui/button"

export default function LlmResponse({ answer }) {
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
					<Button
						className="rounded-2xl text-accent"
						variant={"outline"}
						onClick={() => {
							navigator.clipboard.writeText(answer)
						}}
					>
						<Clipboard />
					</Button>
				</div>
			</div>
		</motion.div>
	)
}
