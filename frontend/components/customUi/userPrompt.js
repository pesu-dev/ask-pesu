import { Edit, User } from "lucide-react"
import { Button } from "../ui/button"

export default function UserPrompt({ query, handleEditQuery }) {
	return (
		<div className="flex items-center justify-end gap-4">
			<Button
				className="rounded-4xl"
				variant={"ghost"}
				onClick={() => {
					handleEditQuery(query)
				}}
			>
				<Edit />
			</Button>
			<div className="min-w-10 p-4 ring ring-accent bg-primary text-primary-foreground rounded-2xl">
				<p>{query}</p>
			</div>
			<User className="ring-2 ring-ring/40 text-ring rounded-full p-2 min-w-10 min-h-10 hidden md:block" />
		</div>
	)
}
