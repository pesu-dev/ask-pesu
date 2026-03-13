import { Bot, Clipboard, ChevronDown, ChevronUp, Loader2 } from "lucide-react"
import { motion, AnimatePresence } from "motion/react"
import ReactMarkdown from "react-markdown"
import { Button } from "../ui/button"
import React, { useMemo, useRef, useState, useEffect } from "react"
import remarkMath from "remark-math"
import rehypeKatex from "rehype-katex"
import "katex/dist/katex.min.css"
import remarkGfm from "remark-gfm"

const STYLE = (
	<style>{`
    @keyframes _wIn {
      from { opacity: 0; transform: translateY(3px); }
      to   { opacity: 1; transform: none; }
    }
    ._w { animation: _wIn 0.14s ease-out both; display: inline; }
  `}</style>
)

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
	const stableCountRef = useRef(0)
	const counterRef = useRef(0)
	counterRef.current = 0

	useEffect(() => {
		stableCountRef.current = counterRef.current
	})

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

	const renderAnimatedWords = (node, baseKey, shouldAnimate = true) => {
		if (typeof node !== "string" || !shouldAnimate) return node
		const stable = stableCountRef.current

		return node.split(/(\s+)/).map((word, i) => {
			const idx = counterRef.current++
			if (idx < stable) return word

			const delay = (idx - stable) * 12
			return (
				<span
					key={`${baseKey}-${i}`}
					className="_w"
					style={{ animationDelay: `${delay}ms` }}
				>
					{word}
				</span>
			)
		})
	}

	const markdownComponents = useMemo(
		() => ({
			a: LinkRenderer,
			li: ListItemRenderer,
			p: ({ children }) => (
				<p>
					{React.Children.map(children, (c, i) =>
						renderAnimatedWords(c, i, isStreaming)
					)}
				</p>
			),
			h1: ({ children }) => (
				<h1>
					{React.Children.map(children, (c, i) =>
						renderAnimatedWords(c, i, isStreaming)
					)}
				</h1>
			),
			h2: ({ children }) => (
				<h2>
					{React.Children.map(children, (c, i) =>
						renderAnimatedWords(c, i, isStreaming)
					)}
				</h2>
			),
			h3: ({ children }) => (
				<h3>
					{React.Children.map(children, (c, i) =>
						renderAnimatedWords(c, i, isStreaming)
					)}
				</h3>
			),
			code: ({ inline, className, children, ...props }) => {
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
		}),
		[answer, isStreaming]
	)

	const answerText = (answer || "").trim()
	const stepsText = (steps || "").trim()

	const showThinkingAnswerPlaceholder =
		isStreaming && !answerText && !!stepsText

	return (
		<>
			{STYLE}
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

					<div className="bg-card px-4 py-3 rounded-2xl text-card-foreground text-base leading-relaxed prose dark:prose-invert wrap-anywhere">
						{showThinkingAnswerPlaceholder ? (
							<div className="flex items-center gap-2 text-muted-foreground not-prose">
								<Loader2 className="h-4 w-4 animate-spin" />
								<span className="text-sm">
									Generating final answer...
								</span>
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

						{answerText && (
							<Button
								className="rounded-2xl text-card-foreground hover:text-card-foreground/50 cursor-pointer"
								variant="outline"
								onClick={() =>
									navigator.clipboard.writeText(answer)
								}
							>
								<Clipboard />
							</Button>
						)}
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
		</>
	)
}
