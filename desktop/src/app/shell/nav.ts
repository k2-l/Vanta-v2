import {
  MessageSquare,
  Activity,
  ShieldCheck,
  Package,
  Boxes,
  Settings,
  type LucideIcon,
} from "lucide-react";

export type NavItem = {
  to: string;
  label: string;
  icon: LucideIcon;
};

/** 六个主导航区域（方案 §21 体验验收）。 */
export const NAV_ITEMS: NavItem[] = [
  { to: "/chat", label: "对话", icon: MessageSquare },
  { to: "/runs", label: "运行", icon: Activity },
  { to: "/approvals", label: "审批", icon: ShieldCheck },
  { to: "/artifacts", label: "产物", icon: Package },
  { to: "/capabilities", label: "能力", icon: Boxes },
  { to: "/settings", label: "设置", icon: Settings },
];
