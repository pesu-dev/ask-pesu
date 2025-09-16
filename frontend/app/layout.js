import { Ubuntu } from "next/font/google"
import { Toaster } from "sonner"
import "./globals.css"

const font = Ubuntu({
	variable: "--font-inter",
	subsets: ["latin"],
	weight: "400",
})

export const metadata = {
	title: "Ask PESU",
	description:
		"A chat bot created exclusively to help students learn more about their college -- PESU",
}

export default function RootLayout({ children }) {
	return (
		<html lang="en">
			<body className={`${font.className} antialiased dark`}>
				{children}
				<Toaster position="top-center" />
			</body>
		</html>
	)
}
