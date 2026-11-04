variable "region" {
  description = "AWS region for everything."
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Name prefix for resources."
  type        = string
  default     = "lexintake-aws"
}

variable "budget_email" {
  description = "Email that receives the AWS Budgets alerts. Set it in terraform/terraform.tfvars (gitignored)."
  type        = string

  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.budget_email))
    error_message = "budget_email must be a valid email address."
  }
}

variable "budget_limit_usd" {
  description = "Monthly cost budget in USD."
  type        = number
  default     = 5
}
