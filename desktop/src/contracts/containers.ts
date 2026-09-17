/** Container runtime wire contracts. Field names follow the FastAPI JSON API. */

export type ContainerWire = {
  id: string;
  name: string;
  image?: string;
  status?: string;
  managed?: boolean;
  ports?: string[];
  env_vars?: string[];
  container_id?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type CreateContainerInput = {
  name: string;
  image: string;
  ports: string[];
  env_vars: string[];
  command: string[] | null;
  network_mode: "bridge" | "none";
  working_dir: string;
};

export type ContainerProfileWire = {
  container_record_id: string;
  capabilities: string[];
  purpose: string;
  workspace_mode: "none" | "read-only" | "read-write";
  network_policy: "none" | "internet";
  default_workdir: string;
  agent_allowlist: string[];
  max_concurrency: number;
  agent_ready: boolean;
  health_status: string;
  active_leases: number;
  created_at?: string | null;
  updated_at?: string | null;
};

export type ContainerProfileInput = Omit<
  ContainerProfileWire,
  | "container_record_id"
  | "health_status"
  | "active_leases"
  | "created_at"
  | "updated_at"
>;

export type ContainerReadiness = {
  ready: boolean;
  reason: string;
  network_mode: string;
  network_access: "not_checked" | "disabled" | "available" | "unavailable" | string;
};
