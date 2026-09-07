// Empty state with example questions, shown before the first message.
import { motion } from "framer-motion";
import { useIsMobile } from "@/hooks/use-mobile";
import { BookOpen, GraduationCap, Calendar, HelpCircle } from "lucide-react";

interface WelcomeScreenProps {
  visible: boolean;
  onSuggestionClick?: (text: string) => void;
}

const suggestions = [
  { icon: BookOpen, text: "What courses does PESU offer in Computer Science?" },
  { icon: GraduationCap, text: "Tell me about the placement statistics at PESU" },
  { icon: Calendar, text: "What are the important dates for admissions?" },
  { icon: HelpCircle, text: "How is campus life at PES University?" },
];

export function WelcomeScreen({ visible, onSuggestionClick }: WelcomeScreenProps) {
  if (!visible) return null;
  const isMobile = useIsMobile();

  return (
    <motion.div
      initial={{ opacity: 1 }}
      exit={{ opacity: 0, scale: 0.95, filter: "blur(10px)" }}
      transition={{ duration: 0.4, ease: "easeInOut" }}
      className="flex flex-1 flex-col items-center justify-center select-none px-4"
    >
      <motion.div
        initial={isMobile ? { opacity: 1, y: 0 } : { opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, delay: 0.1 }}
        className="flex flex-col items-center"
      >
        <h1>
          <span
            className="text-4xl md:text-7xl tracking-wide text-foreground"
            style={{ fontFamily: "'Capriola', sans-serif" }}
          >
            ask
          </span>
          <span
            className="text-4xl md:text-7xl tracking-wide text-primary"
            style={{ fontFamily: "'Capriola', sans-serif" }}
          >
            PESU
          </span>
        </h1>
      </motion.div>

      {/* Suggestions */}
      <motion.div
        initial={isMobile ? { opacity: 1 } : { opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, delay: 0.3 }}
        className="mt-8 grid grid-cols-1 sm:grid-cols-2 gap-2.5 w-full max-w-lg"
      >
        {suggestions.map((s) => (
          <button
            key={s.text}
            onClick={() => onSuggestionClick?.(s.text)}
            className="flex items-start gap-3 rounded-xl border border-border bg-muted/30 px-4 py-3 text-left text-sm text-muted-foreground hover:text-foreground hover:bg-muted/60 hover:border-primary/20 transition-all duration-200 active:scale-[0.98]"
          >
            <s.icon className="h-4 w-4 mt-0.5 shrink-0 text-primary/60" />
            <span className="leading-snug">{s.text}</span>
          </button>
        ))}
      </motion.div>
    </motion.div>
  );
}
