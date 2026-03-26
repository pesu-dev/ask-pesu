import { Bot, Clipboard, ChevronDown, ChevronUp, Loader2 } from "lucide-react"
import { motion, AnimatePresence } from "motion/react"
import ReactMarkdown from "react-markdown"
import { Button } from "../ui/button"
import React, { useMemo, useRef, useState, useEffect } from "react"
import remarkMath from "remark-math"
import rehypeKatex from "rehype-katex"
import "katex/dist/katex.min.css"
import remarkGfm from "remark-gfm"

export default function LlmResponse({
	answer,
	steps,
	handleThinkMode,
	showThinkMoreOption = false,
	isStreaming = false,
	hasReceivedBytes = false,
	wasThinkingMode = false,
}) {
	const [showThinking, setShowThinking] = useState(false)
	const [displayText, setDisplayText] = useState("")
	const indexRef = useRef(0)

	useEffect(() => {
		if (!isStreaming) {
			setDisplayText(answer)
			return
		}

		let timeoutId

		const step = () => {
			const full = answer || ""

			if (indexRef.current < full.length) {
				const nextChunk = full.slice(
					indexRef.current,
					indexRef.current + 5
				)

				indexRef.current += 5

				setDisplayText((prev) => prev + nextChunk)
				timeoutId = setTimeout(step, 12) // TODO: enhance
			}
		}

		step()

		return () => clearTimeout(timeoutId)
	}, [answer, isStreaming])

	const isValidUrl = (string) => {
		try {
			new URL(string)
			return true
		} catch (_) {
			return false
		}
	}

	const LinkRenderer = ({ href, children }) => (
		<a
			href={href}
			target="_blank"
			rel="noopener noreferrer"
			className="text-blue-500 hover:text-blue-700 underline"
		>
			{children}
		</a>
	)

	const ListItemRenderer = ({ children }) => {
		const textContent = React.Children.toArray(children)
			.map((c) => (typeof c === "string" ? c : ""))
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

		return <li>{children}</li>
	}

	const markdownComponents = useMemo(
		() => ({
			a: LinkRenderer,
			li: ListItemRenderer,
			p: ({ children }) => <p>{children}</p>,
			h1: ({ children }) => <h1>{children}</h1>,
			h2: ({ children }) => <h2>{children}</h2>,
			h3: ({ children }) => <h3>{children}</h3>,
			pre: ({ children }) => (
				<pre className="bg-muted p-4 rounded-lg overflow-x-auto my-2">
					{children}
				</pre>
			),
			code: ({ className, children, ...props }) => {
				if (!className) {
					return (
						<code
							className="bg-muted px-1 py-0.5 rounded text-sm"
							{...props}
						>
							{children}
						</code>
					)
				}
				return (
					<code className={className} {...props}>
						{children}
					</code>
				)
			},
		}),
		[answer, isStreaming]
	)

	const answerText = (answer || "").trim()
	const stepsText = (steps || "").trim()

	const showThinkingAnswerPlaceholder =
		isStreaming && !answerText && !!stepsText

	return (
		<motion.div
			initial={{ opacity: 0, x: -30 }}
			animate={{ opacity: 1, x: 0 }}
			className="flex justify-start mt-3 gap-4"
		>
			<Bot className="rounded-full p-2 hidden md:block min-w-10 min-h-10 ring-2 ring-accent/40 text-accent" />
			<div className="flex flex-col flex-nowrap gap-4">
				{steps && wasThinkingMode && (
					<div className="rounded-xl border border-border overflow-hidden w-fit">
						<button
							onClick={() => setShowThinking((p) => !p)}
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
				<div className="bg-card px-4 py-3 rounded-2xl text-card-foreground text-base leading-relaxed prose dark:prose-invert wrap-anywhere transition-opacity duration-200 ease-out">
					{showThinkingAnswerPlaceholder ? (
						<div className="flex items-center gap-2 text-muted-foreground not-prose">
							<Loader2 className="h-4 w-4 animate-spin" />
							<span className="text-sm">
								Generating final answer...
							</span>
						</div>
					) : answerText ? (
						<>
							{isStreaming ? (
								<div className="whitespace-pre-wrap stream-text">
									{displayText}
								</div>
							) : (
								<ReactMarkdown
									remarkPlugins={[remarkGfm, remarkMath]}
									rehypePlugins={[rehypeKatex]}
									components={markdownComponents}
								>
									{answer}
								</ReactMarkdown>
							)}
							<Button
								className="rounded-2xl text-card-foreground hover:text-card-foreground/50 cursor-pointer"
								variant="outline"
								onClick={() =>
									navigator.clipboard.writeText(answer)
								}
							>
								<Clipboard />
							</Button>
						</>
					) : null}
				</div>

				{showThinkMoreOption && (
					<div className="flex gap-4">
						<Button
							className="rounded-4xl"
							variant="outline"
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
