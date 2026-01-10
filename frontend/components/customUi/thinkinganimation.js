import { motion } from "motion/react"
import { Bot } from "lucide-react"

export default function ThinkingIndicator() {
    return (
        <motion.div
            initial={{ opacity: 0, x: -30 }}
            animate={{ opacity: 1, x: 0 }}
            className="flex justify-start mt-3 gap-4"
        >
            <Bot className="rounded-full p-2 hidden md:block min-w-10 min-h-10 ring-2 ring-accent/40 text-accent" />
            <div className="bg-muted px-4 py-3 rounded-2xl text-neutral-500 shadow flex items-center gap-2">
                <span>Thinking</span>
                <div className="flex gap-1">
                    {[0, 0.2, 0.4].map((delay, i) => (
                        <motion.div
                            key={i}
                            className="w-1 h-1 bg-neutral-500 rounded-full"
                            animate={{
                                y: [0, -8, 0],
                            }}
                            transition={{
                                duration: 0.6,
                                repeat: Infinity,
                                delay: delay,
                                ease: "easeInOut",
                            }}
                        />
                    ))}
                </div>
            </div>
        </motion.div>
    )
}
