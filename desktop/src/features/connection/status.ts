/**
 * 连接状态 → 展示元数据（规范 §9.2）。标题栏与状态徽标共用，避免各处散落。
 */

import type { ConnectionStatus } from "@/contracts/connection";
import type { Tone } from "@/components/desktop/status";

export const CONNECTION_STATUS_META: Record<ConnectionStatus, { label: string; tone: Tone }> = {
  unconfigured: { label: "未配置", tone: "neutral" },
  testing: { label: "测试中", tone: "warn" },
  unauthenticated: { label: "未登录", tone: "warn" },
  authenticating: { label: "登录中", tone: "warn" },
  online: { label: "在线", tone: "ok" },
  degraded: { label: "降级", tone: "warn" },
  offline: { label: "离线", tone: "danger" },
  reconnecting: { label: "重连中", tone: "warn" },
};
