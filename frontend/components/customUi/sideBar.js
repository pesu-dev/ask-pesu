"use client"

import { MessageSquare, Plus, Trash2 } from "lucide-react"
import { Button } from "../ui/button"

export default function Sidebar({
	chatSessions,
	currentSessionId,
	onSelectChat,
	onNewChat,
	onDeleteChat,
}) {
	return (
		<div className="w-64 bg-muted/20 border-r border-border h-screen flex flex-col p-4">
			<Button
				onClick={onNewChat}
				className="w-full flex items-center justify-start gap-2 mb-6"
				variant="default"
			>
				<Plus className="w-4 h-4" />
				New Chat
			</Button>

			<div className="flex-1 overflow-y-auto flex flex-col gap-2">
				<h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2 px-2">
					Recent Chats
				</h3>

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
							<span className="text-sm truncate">
								{session.title || "New Conversation"}
							</span>
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
