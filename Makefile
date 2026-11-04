TF = terraform -chdir=terraform

.PHONY: init fmt validate plan deploy destroy

init:
	$(TF) init

fmt:
	$(TF) fmt

validate: init
	$(TF) validate

# Shows what would change. Creates nothing.
plan: init
	$(TF) plan

# Creates everything. Terraform shows the plan and asks you to type "yes".
# (Phase 2 adds the Lambda build step in front of this.)
deploy: init
	$(TF) apply

# Deletes everything Terraform created (asks you to type "yes").
destroy: init
	$(TF) destroy
