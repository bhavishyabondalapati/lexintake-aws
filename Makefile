PROFILE ?= sky
TF = terraform -chdir=terraform

# Terraform can't read `aws login` credentials directly, so export them as environment variables
# for the duration of each command. Run `aws login --profile sky` first (credentials last 12 hours).
AWS_ENV = eval "$$(aws configure export-credentials --profile $(PROFILE) --format env)" && export AWS_REGION=us-east-1

.PHONY: init fmt validate plan deploy destroy

init:
	$(TF) init -input=false

fmt:
	$(TF) fmt

validate: init
	$(TF) validate

# Shows what would change. Creates nothing.
plan: init
	$(AWS_ENV) && $(TF) plan

# Creates everything. Terraform shows the plan and asks you to type "yes".
# (Phase 2 adds the Lambda build step in front of this.)
deploy: init
	$(AWS_ENV) && $(TF) apply

# Deletes everything Terraform created (asks you to type "yes").
destroy: init
	$(AWS_ENV) && $(TF) destroy
