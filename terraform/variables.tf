variable "region" {
  description = "AWS region for everything."
  type        = string
  default     = "us-east-2"
}

variable "project" {
  description = "Name prefix for resources."
  type        = string
  default     = "lexintake-aws"
}

variable "anthropic_model" {
  description = "Claude model used by the extract Lambda (classification + NDA fields in one call)."
  type        = string
  default     = "claude-sonnet-5-5"
}

variable "max_upload_mb" {
  description = "Largest PDF accepted, in MB. Enforced when the upload URL is issued and again by the parse Lambda."
  type        = number
  default     = 10
}
