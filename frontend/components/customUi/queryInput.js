import { SendHorizonal } from "lucide-react"
import { Button } from "../ui/button"
import { CustomTextarea } from "./customTextarea"
import useSWR from "swr"
import { useEffect, useState } from "react"
import { toast } from "sonner"

export default function QueryInput({
	query,
	setQuery,
	modelChoice,
	setModelChoice,
	loading,
	handleQuery,
}) {
	const fetcher = (...args) => fetch(...args).then((res) => res.json())
	const API_URL = process.env.NEXT_PUBLIC_DEV_API_URL
	const url = `${API_URL}/quota`
	const { data, error, swrIsLoading } = useSWR(url, fetcher)

	const [thinkingAllowed, setThinkingAllowed] = useState(false)

	useEffect(() => {
		if (error) console.error("SWR ERROR: ", error)
	}, [error])

	useEffect(() => {
		if (swrIsLoading) return

		if (!data) return

		if (!data.status) {
			console.error(data)
			toast.error(data?.message)
			setThinkingAllowed(false)
			return
		}

		if (data?.quota?.thinking?.available) {
			setThinkingAllowed(true)
			return
		}

		setThinkingAllowed(false)
	}, [data, swrIsLoading])

	useEffect(() => {
		if (!thinkingAllowed) {
			setModelChoice("primary")
		}
	}, [thinkingAllowed, setModelChoice])

	return (
		<div
			className={`flex flex-nowrap flex-col w-[90vw] max-w-4xl max-h-[30vh] overflow-y-auto hide-scrollbar mx-auto bg-background px-4 py-2 ring-2 ${
				loading
					? "ring-muted"
					: "ring-primary/50 focus-within:ring-blue-500"
			} rounded-2xl transition-all duration-200 ${
				loading ? "opacity-60" : ""
			}`}
		>
			<div className="flex flex-nowrap gap-5">
				<CustomTextarea
					disabled={loading}
					className="w-full text-lg border-none focus:outline-none focus-visible:ring-0"
					placeholder={
						loading
							? "Service temporarily unavailable..."
							: "What would you like to know about PESU?"
					}
					value={query}
					onChange={(e) => setQuery(e.target.value)}
					onKeyDown={(e) => {
						if (e.key === "Enter" && !loading) {
							e.preventDefault()
							handleQuery()
						}
					}}
				/>
				<Button
					disabled={loading}
					className="rounded-l-none rounded-full w-12 h-10"
					onClick={() => handleQuery()}
				>
					<SendHorizonal className="size-4" />
				</Button>
			</div>
			<div>
				{/* <Select
					value={modelChoice}
					onValueChange={(v) => {
						setModelChoice(v)
					}}
					disabled={!thinkingAllowed || swrIsLoading}
				>
					<SelectTrigger id="model-select" className="w-56">
						<SelectValue placeholder="Select model" />
					</SelectTrigger>
					<SelectContent>
						<SelectGroup>
							<SelectLabel>Model Choice</SelectLabel>
							<SelectItem value="primary">
								Primary model
							</SelectItem>
							<SelectItem value="thinking">
								Thinking model
							</SelectItem>
						</SelectGroup>
					</SelectContent>
				</Select> */}
			</div>
		</div>
	)
}
