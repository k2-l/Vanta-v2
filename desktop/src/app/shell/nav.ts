import {
  MessageSquare,
  Activity,
  ShieldCheck,
  Package,
  Boxes,
  Settings,
  type LucideIcon,
} from "lucide-react";
import type { ModuleId } from "@/stores/ui";

export type NavItem = {
  id: ModuleId;
  to: string;
  label: string;
  icon: LucideIcon;
};

/** 六个一级模块，顺序固定（规范 §2）。 */
export const NAV_ITEMS: NavItem[] = [
  { id: "chat", to: "/chat", label: "对话", icon: MessageSquare },
  { id: "runs", to: "/runs", label: "运行", icon: Activity },
  { id: "approvals", to: "/approvals", label: "审批", icon: ShieldCheck },
  { id: "artifacts", to: "/artifacts", label: "产物", icon: Package },
  { id: "capabilities", to: "/capabilities", label: "能力", icon: Boxes },
  { id: "settings", to: "/settings", label: "设置", icon: Settings },
];
