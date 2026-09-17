/** Skill wire 契约。字段与 harness/routes/skills.py 的 _skill_dict / SkillPatch 逐字段对齐。 */

export type SkillWire = {
  id: string;
  name: string;
  description: string;
  content: string;
  model: string;
  allowed_tools: string[];
  argument_hint: string;
  disable_model_invocation: boolean;
  user_invocable: boolean;
};

/** PATCH /v1/skills/{id} 请求体（对应后端 SkillPatch，仅这些字段可改）。 */
export type SkillPatchInput = {
  name: string;
  description: string;
  content: string;
  allowed_tools: string[];
  model: string;
  argument_hint: string;
};
