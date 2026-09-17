export type McpToolWire = {
  name: string;
  remote_name: string;
};

export type McpServerWire = {
  name: string;
  command: string;
  args: string[];
  enabled: boolean;
  env_keys: string[];
  status: "connected" | "disconnected" | "error" | string;
  error: string | null;
  tool_count: number;
  tools?: McpToolWire[];
};

export type McpServerCreateInput = {
  name: string;
  command: string;
  args: string[];
  env: Record<string, string>;
  enabled: boolean;
  confirm: true;
};

export type McpServerPatchInput = {
  command: string;
  args: string[];
  env?: Record<string, string>;
  enabled: boolean;
  confirm: true;
};

export type McpTestResult = {
  ok: boolean;
  error: string | null;
  tools: string[];
};
