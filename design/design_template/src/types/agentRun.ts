interface AgentRunResponse {
  agent_run_id: string
  decision_context_id: string
  agent_type: string
  started_at: string
  model_id: string | null
  prompt_id: string | null
  temperature: number | null
  seed: number | null
  raw_output_uri: string | null
  structured_output_json: Record<string, unknown> | null
  status: string
  completed_at: string | null
  created_at: string | null
}

export type { AgentRunResponse }
