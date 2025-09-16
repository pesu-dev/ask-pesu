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
			<div className="min-w-10 bg-card p-4 ring ring-accent rounded-4xl">
				<p>{query}</p>
			</div>
			<User className="border rounded-full p-2 size-10 min-w-10 min-h-10" />
		</div>
	)
}
