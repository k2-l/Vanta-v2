import { createHashRouter, RouterProvider } from "react-router-dom";
import { AppShell } from "./shell/AppShell";

/**
 * HashRouter：Tauri WebView 用 file/自定义 scheme，hash 路由最稳。
 * 六个主导航区域（方案 §21）：chat / runs / approvals / artifacts / capabilities / settings。
 */
const router = createHashRouter([{ path: "*", element: <AppShell /> }]);

export function AppRouter() {
  return <RouterProvider router={router} />;
}
