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

variable "my_ip_cidr" {
  description = "The only address allowed to open the review app, as a CIDR such as 203.0.113.7/32. The Makefile fills it in with your current public IP."
  type        = string

  validation {
    condition     = can(cidrhost(var.my_ip_cidr, 0)) && var.my_ip_cidr != "0.0.0.0/0"
    error_message = "my_ip_cidr must be a valid CIDR and must not be 0.0.0.0/0 (the app has no login)."
  }
}

variable "daily_doc_limit" {
  description = "Most documents the review app will accept per UTC day, so the demo can't burn API credit."
  type        = number
  default     = 20
}
