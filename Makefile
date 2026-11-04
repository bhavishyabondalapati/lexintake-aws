PROFILE ?= sky
TF = terraform -chdir=terraform
PYTHON ?= python3
# The conda environment for tests (named after the folder, see README).
CONDA_PY = conda run --no-capture-output -n $(notdir $(CURDIR))

# Terraform can't read `aws login` credentials directly, so export them as environment variables
# for the duration of each command. Run `aws login --profile sky` first (credentials last 12 hours).
#
# The review app accepts connections only from your current public IP (override: MY_IP_CIDR=1.2.3.4/32).
MY_IP_CIDR ?= $(shell curl -fsS https://checkip.amazonaws.com | tr -d '[:space:]')/32
AWS_ENV = eval "$$(aws configure export-credentials --profile $(PROFILE) --format env)" && export AWS_REGION=us-east-2 TF_VAR_my_ip_cidr=$(MY_IP_CIDR)

.PHONY: init fmt validate plan deploy destroy build test sample review

init:
	$(TF) init -input=false

fmt:
	$(TF) fmt

# Packages the Lambdas into build/ (needs only python3 + pip; works on a clean checkout).
build:
	PYTHON=$(PYTHON) scripts/build_lambdas.sh

validate: init build
	$(TF) validate

# Shows what would change. Creates nothing.
plan: init build
	$(AWS_ENV) && $(TF) plan

# Creates everything. Terraform shows the plan and asks you to type "yes".
deploy: init build
	$(AWS_ENV) && $(TF) apply

# Deletes everything Terraform created (asks you to type "yes").
destroy: init build
	$(AWS_ENV) && $(TF) destroy

test:
	$(CONDA_PY) python -m pytest -q

# Upload a PDF and watch it go through the pipeline: make sample [FILE=path/to.pdf]
sample:
	$(AWS_ENV) && scripts/run_sample.sh $(FILE)

# Resolve a document waiting for review: make review DOC=<doc_id> ACTION=approve|reject
review:
	$(AWS_ENV) && scripts/review.sh $(ACTION) $(DOC)
