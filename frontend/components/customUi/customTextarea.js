import * as React from "react"

import { cn } from "@/lib/utils"

const CustomTextarea = React.forwardRef(({ className, ...props }, ref) => {
	return (
		<textarea
			ref={ref}
			data-slot="textarea"
			className={cn(
				"resize-none placeholder:text-muted-foreground flex field-sizing-content min-h-16 w-full rounded-md border bg-transparent px-3 py-2 text-base shadow-xs transition-[color,box-shadow] outline-none disabled:cursor-not-allowed disabled:opacity-50",
				className
			)}
			{...props}
		/>
	)
})

CustomTextarea.displayName = "CustomTextarea"

export { CustomTextarea }
