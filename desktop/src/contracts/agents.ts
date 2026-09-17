/** Agent wire contracts. These fields map directly to the AGENT.md provider model. */

export type AgentWire = {
  id: string;
  name: string;
  description: string;
  content: string;
  model: string;
  provider: "anthropic" | "openai" | null;
  tools: string[];
  enable_critic: boolean;
  disable_model_invocation: boolean;
  user_invocable: boolean;
};

export type AgentPatchInput = {
  name: string;
  description: string;
  content: string;
  tools: string[];
  model: string;
  provider: "anthropic" | "openai" | null;
  enable_critic: boolean;
  disable_model_invocation: boolean;
  user_invocable: boolean;
};
