import { createHashRouter, Navigate, RouterProvider } from "react-router-dom";
import { AppShell } from "./shell/AppShell";
import { ChatPage } from "@/pages/chat";
import { RunsPage } from "@/pages/runs";
import { ApprovalsPage } from "@/pages/approvals";
import { ArtifactsPage } from "@/pages/artifacts";
import { CapabilitiesPage } from "@/pages/capabilities";
import { SettingsPage } from "@/pages/settings";

/**
 * HashRouter：Tauri WebView 用 file/自定义 scheme，hash 路由最稳。
 * 六个主导航区域（方案 §21）：chat / runs / approvals / artifacts / capabilities / settings。
 */
const router = createHashRouter([
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/chat" replace /> },
      { path: "chat", element: <ChatPage /> },
      { path: "runs", element: <RunsPage /> },
      { path: "approvals", element: <ApprovalsPage /> },
      { path: "artifacts", element: <ArtifactsPage /> },
      { path: "capabilities", element: <CapabilitiesPage /> },
      { path: "settings", element: <SettingsPage /> },
      { path: "*", element: <Navigate to="/chat" replace /> },
    ],
  },
]);

export function AppRouter() {
  return <RouterProvider router={router} />;
}
