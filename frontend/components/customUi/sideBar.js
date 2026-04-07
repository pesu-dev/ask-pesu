"use client"

import {
	MessageSquare,
	Plus,
	Trash2,
	Loader2,
	ChevronLeft,
	ChevronRight,
} from "lucide-react"
import { Button } from "../ui/button"

export default function Sidebar({
	chatSessions,
	currentSessionId,
	onSelectChat,
	onNewChat,
	onDeleteChat,
	isSidebarExpanded,
	setIsSidebarExpanded,
}) {
	return (
		<div
			className={`${isSidebarExpanded ? "w-96" : "w-64"} shrink-0 transition-[width] duration-300 ease-in-out bg-muted/20 border-r border-border h-screen flex flex-col p-4`}
		>
			<Button
				onClick={onNewChat}
				className="w-full flex items-center justify-start gap-2 mb-6"
				variant="default"
			>
				<Plus className="w-4 h-4" />
				New Chat
			</Button>

			<div className="flex-1 overflow-y-auto flex flex-col gap-2">
				<div className="flex items-center justify-between mb-2 px-2">
					<h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
						Recent Chats
					</h3>
					<button
						onClick={() => setIsSidebarExpanded(!isSidebarExpanded)}
						className="p-1 hover:bg-muted/80 rounded-md text-muted-foreground transition-colors"
					>
						{isSidebarExpanded ? <ChevronLeft className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
					</button>
				</div>

				{chatSessions?.map((session) => (
					<div
						key={session.id}
						className={`group flex items-center justify-between p-2 rounded-lg cursor-pointer transition-colors ${
							currentSessionId === session.id
								? "bg-accent text-accent-foreground"
								: "hover:bg-muted/50 text-muted-foreground hover:text-foreground"
						}`}
						onClick={() => onSelectChat(session.id)}
					>
						<div className="flex items-center gap-2 overflow-hidden">
							<MessageSquare className="w-4 h-4 shrink-0" />
							{session.isGeneratingTitle ? (
								<Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
							) : (
								<span className="text-sm truncate">
									{session.title || "New Conversation"}
								</span>
							)}
						</div>
						<button
							onClick={(e) => {
								e.stopPropagation()
								onDeleteChat(session.id)
							}}
							className="opacity-0 group-hover:opacity-100 p-1 hover:text-destructive transition-opacity"
						>
							<Trash2 className="w-4 h-4" />
						</button>
					</div>
				))}
			</div>
		</div>
	)
}
