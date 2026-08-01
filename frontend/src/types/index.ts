export interface Token {
  access_token: string
  token_type: string
  role: string
  display_name?: string | null
}

export interface Healthz {
  status: string
  db: string
}

export interface Project {
  id: string
  name: string
  code?: string | null
  status: string
  total_investment?: number | null
}

export interface ProjectList {
  items: Project[]
  total: number
}
