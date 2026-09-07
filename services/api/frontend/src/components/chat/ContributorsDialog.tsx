// Credits dialog listing project contributors.
import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, Anchor } from "lucide-react";
import { SiGithub } from "@icons-pack/react-simple-icons";

interface Contributor {
  name: string;
  role: string;
  links?: { icon: "github" | "anchor"; url: string }[];
}

const contributors: Contributor[] = [
  { name: "Joshua Raj", role: "Project Lead" },
  { name: "Rowlett Owl / Moss", role: "Contributor" },
  { name: "M Night Shyamalan", role: "Contributor" },
  { name: "Woduh", role: "Contributor" },
  { name: "dotpmm", role: "Contributor" },
  {
    name: "DarkSpacepirate",
    role: "Contributor",
    links: [
      { icon: "github", url: "https://github.com/Thanas-R" },
      { icon: "anchor", url: "https://thanas.vercel.app/" },
    ],
  },
  { name: "Kedar Chitnis", role: "Logo Designer" },
];

interface ContributorsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function ContributorsDialog({ open, onOpenChange }: ContributorsDialogProps) {
  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="fixed inset-0 z-[100] bg-black/40 backdrop-blur-sm"
            onClick={() => onOpenChange(false)}
          />
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 10 }}
            transition={{ duration: 0.25, ease: [0.4, 0, 0.2, 1] }}
            className="fixed inset-0 z-[101] flex items-center justify-center p-4"
          >
            <div className="w-full max-w-sm rounded-2xl border border-border bg-card p-5 shadow-xl">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-base font-semibold text-foreground">Contributors</h3>
                <button
                  title="Close"
                  onClick={() => onOpenChange(false)}
                  className="rounded-lg p-1 hover:bg-muted transition-colors"
                >
                  <X className="h-4 w-4 text-muted-foreground" />
                </button>
              </div>
              <div className="space-y-1">
                {contributors.map((c) => (
                  <div
                    key={c.name}
                    className="flex items-center justify-between rounded-xl px-3 py-2.5 hover:bg-muted/50 transition-colors"
                  >
                    <div>
                      <p className="text-sm font-medium text-foreground">{c.name}</p>
                      <p className="text-xs text-muted-foreground">{c.role}</p>
                    </div>
                    {c.links && (
                      <div className="flex items-center gap-1.5">
                        {c.links.map((link) => (
                          <a
                            key={link.url}
                            href={link.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="rounded-lg p-1.5 hover:bg-muted transition-colors text-muted-foreground hover:text-foreground"
                          >
                            {link.icon === "github" ? (
                              <SiGithub className="h-3.5 w-3.5" />
                            ) : (
                              <Anchor className="h-3.5 w-3.5" />
                            )}
                          </a>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
