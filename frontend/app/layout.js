import { Space_Grotesk } from "next/font/google"
import { Toaster } from "sonner"
import "./globals.css"

const spaceGrotesk = Space_Grotesk({
	variable: "--font-space-grotesk",
	subsets: ["latin"],
})

export const metadata = {
	title: "Ask PESU",
	description:
		"A chat bot created exclusively to help students learn more about their college -- PESU",
}

export default function RootLayout({ children }) {
	return (
		<html lang="en">
			<body className={`${spaceGrotesk.className} antialiased dark`}>
				{children}
				<Toaster position="top-center" />
			</body>
		</html>
	)
}
