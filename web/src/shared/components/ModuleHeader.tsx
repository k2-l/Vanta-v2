/**
 * ModuleHeader — 各模块共用的统一页头（对话 / Agent / 技能 / 知识库 / 容器 / MCP / 记忆 / 配置）。
 *
 * 统一高度(56)、内边距(0 24px)、白底 + 底部分隔线，避免模块切换时顶栏尺寸/样式跳动。
 * title: 左侧标题区（静态标题用 <ModuleTitle>，master-detail 页也可传可编辑输入）。
 * actions: 右侧操作区（新建 / 保存 / 扫描 等按钮）。
 */
import type { CSSProperties, ReactNode } from "react";

export function ModuleHeader({
  title,
  actions,
  style,
}: {
  title: ReactNode;
  actions?: ReactNode;
  style?: CSSProperties;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "0 24px",
        minHeight: 56,
        flexShrink: 0,
        boxSizing: "border-box",
        background: "#FFFFFF",
        borderBottom: "1px solid #E2E5EA",
        ...style,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 12, minWidth: 0, flex: 1 }}>
        {title}
      </div>
      {actions && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
          {actions}
        </div>
      )}
    </div>
  );
}

export function ModuleTitle({ children }: { children: ReactNode }) {
  return (
    <span style={{ fontSize: 16, fontWeight: 700, color: "#1A1D23", whiteSpace: "nowrap" }}>
      {children}
    </span>
  );
}
