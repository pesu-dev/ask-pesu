import { Bot, Clipboard, ChevronDown, ChevronUp } from "lucide-react"
import { motion, AnimatePresence } from "motion/react"
import ReactMarkdown from "react-markdown"
import { Button } from "../ui/button"
import React, { useState } from "react"
import remarkMath from "remark-math"
import rehypeKatex from "rehype-katex"
import "katex/dist/katex.min.css"
import remarkGfm from "remark-gfm"

export default function LlmResponse({
	answer,
	steps,
	handleThinkMode,
	showThinkMoreOption = false,
}) {
	const [showThinking, setShowThinking] = useState(false)

	const isValidUrl = (string) => {
		try {
			new URL(string)
			return true
		} catch (_) {
			return false
		}
	}

	const LinkRenderer = (props) => {
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

	const markdownComponents = {
		a: LinkRenderer,
		li: ListItemRenderer,
		code: ({ node, inline, className, children, ...props }) => {
			if (inline) {
				return (
					<code className="bg-muted px-1 py-0.5 rounded text-sm">
						{children}
					</code>
				)
			}
			return (
				<pre className="bg-muted p-4 rounded-lg overflow-x-auto my-2">
					<code className={className} {...props}>
						{children}
					</code>
				</pre>
			)
		},
	}

	return (
		<motion.div
			initial={{ opacity: 0, x: -30 }}
			animate={{ opacity: 1, x: 0 }}
			className="flex justify-start mt-3 gap-4"
		>
			<Bot className="rounded-full p-2 hidden md:block min-w-10 min-h-10 ring-2 ring-accent/40 text-accent" />
			<div className="flex flex-col flex-nowrap gap-4">
				{/* Thinking dropdown — only if steps exist */}
				{steps && (
					<div className="rounded-xl border border-border overflow-hidden w-fit">
						<button
							onClick={() => setShowThinking((prev) => !prev)}
							className="flex items-center gap-2 px-3 py-2 text-sm text-muted-foreground hover:bg-muted/50 transition-colors cursor-pointer"
						>
							{showThinking
								? "Hide thinking"
								: "Show thinking..."}
							{showThinking ? (
								<ChevronUp className="w-4 h-4" />
							) : (
								<ChevronDown className="w-4 h-4" />
							)}
						</button>
						<AnimatePresence>
							{showThinking && (
								<motion.div
									initial={{ height: 0, opacity: 0 }}
									animate={{ height: "auto", opacity: 1 }}
									exit={{ height: 0, opacity: 0 }}
									transition={{ duration: 0.2 }}
									className="overflow-hidden"
								>
									<div className="px-4 py-3 border-t border-border bg-muted/30 text-sm text-muted-foreground prose dark:prose-invert prose-sm max-w-none">
										<ReactMarkdown
											remarkPlugins={[
												remarkGfm,
												remarkMath,
											]}
											rehypePlugins={[rehypeKatex]}
											components={markdownComponents}
										>
											{steps}
										</ReactMarkdown>
									</div>
								</motion.div>
							)}
						</AnimatePresence>
					</div>
				)}

				{/* Main answer */}
				<div className="bg-card px-4 py-3 rounded-2xl text-card-foreground text-base leading-relaxed prose dark:prose-invert wrap-anywhere">
					<ReactMarkdown
						remarkPlugins={[remarkGfm, remarkMath]}
						rehypePlugins={[rehypeKatex]}
						components={markdownComponents}
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
				{showThinkMoreOption && (
                    <div className="flex gap-4">
                        <Button
                            className="rounded-4xl"
                            variant={"outline"}
                            onClick={handleThinkMode}
                        >
                            Think longer for a better answer
                        </Button>
                    </div>
                )}
			</div>
		</motion.div>
	)
}
