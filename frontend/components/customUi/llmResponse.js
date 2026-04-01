import { Bot, Clipboard, ChevronDown, ChevronUp, Loader2 } from "lucide-react"
import { motion, AnimatePresence } from "motion/react"
import ReactMarkdown from "react-markdown"
import { Button } from "../ui/button"
import React, { useMemo, useState, useEffect, useRef } from "react"
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
	const [displayedText, setDisplayedText] = useState("")

	// Refs to handle our dynamic animation frame queue
	const textToDisplayRef = useRef("")
	const currentDisplayedRef = useRef("")
	const rafRef = useRef(null)

	useEffect(() => {
		textToDisplayRef.current = answer || ""

		// If we are done streaming, snap to the full text and stop the animation loop
		if (!isStreaming) {
			setDisplayedText(answer || "")
			currentDisplayedRef.current = answer || ""
			if (rafRef.current) cancelAnimationFrame(rafRef.current)
			return
		}

		const animateText = () => {
			const target = textToDisplayRef.current
			const current = currentDisplayedRef.current

			if (current.length < target.length) {
				const diff = target.length - current.length
				// The Magic: dynamically adjust typing speed based on the backlog.
				// It catches up by a fraction of the difference per frame, minimum 1 character.
				// This creates an organic acceleration/deceleration effect.
				const charsToAdd = Math.max(3, Math.ceil(diff / 30))

				currentDisplayedRef.current = target.slice(
					0,
					current.length + charsToAdd
				)
				setDisplayedText(currentDisplayedRef.current)
			}

			// Keep the animation loop running as long as we are streaming
			rafRef.current = requestAnimationFrame(animateText)
		}

		if (!rafRef.current) {
			rafRef.current = requestAnimationFrame(animateText)
		}

		return () => {
			if (rafRef.current) cancelAnimationFrame(rafRef.current)
			rafRef.current = null
		}
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
			// Smooth fade-in for list items
			li: ({ children }) => {
				const textContent = React.Children.toArray(children)
					.map((c) => (typeof c === "string" ? c : ""))
					.join("")
					.trim()

				if (isValidUrl(textContent)) {
					return (
						<motion.li
							initial={{ opacity: 0, x: -5 }}
							animate={{ opacity: 1, x: 0 }}
						>
							<a
								href={textContent}
								target="_blank"
								rel="noopener noreferrer"
								className="text-blue-500 hover:text-blue-700 underline"
							>
								{textContent}
							</a>
						</motion.li>
					)
				}
				return (
					<motion.li
						initial={{ opacity: 0, x: -5 }}
						animate={{ opacity: 1, x: 0 }}
					>
						{children}
					</motion.li>
				)
			},
			// Smooth fade and slide up for new paragraphs
			p: ({ children }) => (
				<motion.p
					initial={{ opacity: 0, y: 4 }}
					animate={{ opacity: 1, y: 0 }}
					transition={{ duration: 0.3, ease: "easeOut" }}
					className="mb-2 last:mb-0"
				>
					{children}
				</motion.p>
			),
			h1: ({ children }) => (
				<motion.h1 initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
					{children}
				</motion.h1>
			),
			h2: ({ children }) => (
				<motion.h2 initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
					{children}
				</motion.h2>
			),
			h3: ({ children }) => (
				<motion.h3 initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
					{children}
				</motion.h3>
			),
			// Fade in code blocks so they don't aggressively snap onto the screen
			pre: ({ children }) => (
				<motion.pre
					initial={{ opacity: 0, scale: 0.98 }}
					animate={{ opacity: 1, scale: 1 }}
					transition={{ duration: 0.3 }}
					className="bg-muted p-4 rounded-lg overflow-x-auto my-2"
				>
					{children}
				</motion.pre>
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
		[]
	)

	const stepsText = (steps || "").trim()
	const showThinkingAnswerPlaceholder =
		isStreaming && !textToDisplayRef.current && !!stepsText

	return (
		<motion.div
			initial={{ opacity: 0, x: -30 }}
			animate={{ opacity: 1, x: 0 }}
			className="flex justify-start mt-3 gap-4"
		>
			<Bot className="rounded-full p-2 hidden md:block min-w-10 min-h-10 ring-2 ring-accent/40 text-accent" />
			<div className="flex flex-col flex-nowrap gap-4 w-full max-w-[calc(100%-3rem)]">
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
					) : displayedText ? (
						<div className="relative group">
							<ReactMarkdown
								remarkPlugins={[remarkGfm, remarkMath]}
								rehypePlugins={[rehypeKatex]}
								components={markdownComponents}
							>
								{displayedText}
							</ReactMarkdown>

							{!isStreaming && (
								<Button
									className="absolute -top-2 -right-2 opacity-0 group-hover:opacity-100 transition-opacity rounded-xl text-muted-foreground hover:text-foreground h-8 w-8 p-0"
									variant="secondary"
									onClick={() =>
										navigator.clipboard.writeText(answer)
									}
								>
									<Clipboard className="w-4 h-4" />
								</Button>
							)}
						</div>
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
