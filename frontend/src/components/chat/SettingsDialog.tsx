import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Sun, Moon } from "lucide-react";
import { cn } from "@/lib/utils";

type Theme = "light" | "dark";

interface SettingsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  theme: Theme;
  onThemeChange: (theme: Theme) => void;
  demoEnabled: boolean;
  onDemoEnabledChange: (enabled: boolean) => void;
}

const themes: { value: Theme; label: string; icon: React.ElementType }[] = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
];

export function SettingsDialog({
  open,
  onOpenChange,
  theme,
  onThemeChange,
  demoEnabled,
  onDemoEnabledChange,
}: SettingsDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="text-lg font-semibold">Settings</DialogTitle>
        </DialogHeader>
        <div className="space-y-6 py-4">
          <div>
            <Label className="mb-3 block text-sm font-medium text-foreground">Appearance</Label>
            <div className="flex gap-2">
              {themes.map((t) => (
                <button
                  key={t.value}
                  onClick={() => onThemeChange(t.value)}
                  className={cn(
                    "flex flex-1 flex-col items-center gap-2 rounded-xl border p-3 transition-all outline-none focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/40",
                    theme === t.value
                      ? "border-primary bg-primary/5 text-primary"
                      : "border-border text-muted-foreground hover:border-primary/30"
                  )}
                >
                  <t.icon className="h-5 w-5" />
                  <span className="text-xs font-medium">{t.label}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-3">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <Label className="text-sm">Demo mode</Label>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  Serve pre-generated answers for the four welcome suggestions
                  instead of calling the backend. Useful when the FastAPI
                  service is offline.
                </p>
              </div>
              <Switch checked={demoEnabled} onCheckedChange={onDemoEnabledChange} />
            </div>
            <div className="flex items-center justify-between">
              <Label className="text-sm">Stream responses</Label>
              <Switch defaultChecked />
            </div>
            <div className="flex items-center justify-between">
              <Label className="text-sm">Show sources</Label>
              <Switch defaultChecked />
            </div>
            <div className="flex items-center justify-between">
              <Label className="text-sm">LaTeX rendering</Label>
              <Switch defaultChecked />
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
