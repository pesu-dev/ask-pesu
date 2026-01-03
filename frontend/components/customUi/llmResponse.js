import { Bot, Clipboard } from "lucide-react"
import { motion } from "motion/react"
import ReactMarkdown from "react-markdown"
import { Button } from "../ui/button"
import React from "react"

export default function LlmResponse({
	answer,
	handleThinkMode,
	showThinkMoreOption = false,
}) {
	const isValidUrl = (string) => {
		try {
			new URL(string)
			return true
		} catch (_) {
			return false
		}
	}

	const LinkRenderer = (props) => {
		console.log("Link props:", props)
		return (
			<a
				href={props.href}
				target="_blank"
				rel="noopener noreferrer"
				className="text-blue-500 hover:text-blue-700 underline"
			>
				{props.children}
			</a>
		)
	}

	const ListItemRenderer = (props) => {
		const content = props.children

		// Check if the list item content is a string URL
		if (typeof content === "string" && isValidUrl(content.trim())) {
			return (
				<li>
					<a
						href={content.trim()}
						target="_blank"
						rel="noopener noreferrer"
						className="text-blue-500 hover:text-blue-700 underline"
					>
						{content.trim()}
					</a>
				</li>
			)
		}

		// Check if children contain text that might be a URL
		const textContent = React.Children.toArray(content)
			.map((child) => (typeof child === "string" ? child : ""))
			.join("")
			.trim()

		if (isValidUrl(textContent)) {
			return (
				<li>
					<a
						href={textContent}
						target="_blank"
						rel="noopener noreferrer"
						className="text-blue-500 hover:text-blue-700 underline"
					>
						{textContent}
					</a>
				</li>
			)
		}

		return <li>{content}</li>
	}

	return (
		<motion.div
			initial={{ opacity: 0, x: -30 }}
			animate={{ opacity: 1, x: 0 }}
			className="flex justify-start mt-3 gap-4"
		>
			<Bot className="rounded-full p-2 hidden md:block min-w-10 min-h-10 ring-2 ring-accent/40 text-accent" />
			<div className="flex flex-col flex-nowrap gap-4">
				<div className="bg-card px-4 py-3 rounded-2xl text-card-foreground text-base leading-relaxed prose dark:prose-invert wrap-anywhere">
					<ReactMarkdown
						components={{
							a: LinkRenderer,
							li: ListItemRenderer,
						}}
					>
						{answer}
					</ReactMarkdown>
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
							onClick={handleThinkMode}
						>
							Think longer for a better answer
						</Button>
					</div>
				) : null}
			</div>
		</motion.div>
	)
}
