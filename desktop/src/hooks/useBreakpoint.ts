/**
 * 窗口断点（规范 §5）：
 * - 宽度 < 1100：优先关闭详情面板。
 * - 宽度 < 900：压缩上下文侧栏。
 * 基准 1280×720，推荐最小 960×640。
 */

import { useSyncExternalStore } from "react";

export type Breakpoint = {
  width: number;
  /** 详情面板是否允许展示（窗口够宽）。 */
  canShowDetail: boolean;
  /** 上下文侧栏是否进入压缩态。 */
  compactRail: boolean;
};

const DETAIL_MIN = 1100;
const RAIL_COMPACT_MAX = 900;

function getWidth(): number {
  return typeof window === "undefined" ? 1280 : window.innerWidth;
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener("resize", onChange);
  return () => window.removeEventListener("resize", onChange);
}

export function useBreakpoint(): Breakpoint {
  const width = useSyncExternalStore(subscribe, getWidth, () => 1280);
  return {
    width,
    canShowDetail: width >= DETAIL_MIN,
    compactRail: width < RAIL_COMPACT_MAX,
  };
}
