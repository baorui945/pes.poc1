APP_NAME := flask-rca-demo
NAMESPACE := rca-demo
IMAGE_TAG := latest
HELM_CHART_DIR := ./helm-chart
PLAYBOOK_FILE := ./playbooks/flask-rca-playbook.yaml
PROMETHEUS_RULE := ./monitoring/flask-rca-prometheusrule.yaml

CONTAINER_RUNTIME := $(shell if command -v docker >/dev/null 2>&1; then echo "docker"; elif command -v podman >/dev/null 2>&1; then echo "podman"; else echo "none"; fi)

.PHONY: build-image
build-image:
ifeq ($(CONTAINER_RUNTIME), none)
	$(error Neither docker nor podman found)
endif
	@echo "Building image with $(CONTAINER_RUNTIME)..."
	$(CONTAINER_RUNTIME) build -t $(APP_NAME):$(IMAGE_TAG) .

.PHONY: load-to-k3s
load-to-k3s:
	@if [ "$(CONTAINER_RUNTIME)" = "docker" ]; then \
		sudo ctr images import <($(CONTAINER_RUNTIME) save $(APP_NAME):$(IMAGE_TAG)); \
	elif [ "$(CONTAINER_RUNTIME)" = "podman" ]; then \
		$(CONTAINER_RUNTIME) save $(APP_NAME):$(IMAGE_TAG) | sudo ctr images import -; \
	fi

.PHONY: deploy-app
deploy-app: build-image load-to-k3s
	@echo "Deploying Helm chart..."
	kubectl create namespace $(NAMESPACE) --dry-run=client -o yaml | kubectl apply -f -
	helm upgrade --install $(APP_NAME) $(HELM_CHART_DIR) \
		--namespace $(NAMESPACE) \
		--set image.repository=$(APP_NAME) \
		--set image.tag=$(IMAGE_TAG)

.PHONY: apply-prometheus-rule
apply-prometheus-rule:
	@echo "Applying PrometheusRule..."
	kubectl apply -f $(PROMETHEUS_RULE) -n $(NAMESPACE)

.PHONY: apply-playbook
apply-playbook:
	@echo "Applying Robusta Playbook..."
	robusta playbooks push $(PLAYBOOK_FILE)

.PHONY: test-error
test-error:
	@SVC=$$(kubectl get svc $(APP_NAME) -n $(NAMESPACE) -o jsonpath='{.spec.clusterIP}'); \
	if [ -z "$$SVC" ]; then \
		echo "Service not found!"; exit 1; \
	fi; \
	echo "Triggering DB error..."; \
	curl -s "http://$$SVC:5000/process_order?order_id=test123&error=db"

.PHONY: clean
clean:
	helm uninstall $(APP_NAME) -n $(NAMESPACE) || true
	kubectl delete -f $(PROMETHEUS_RULE) -n $(NAMESPACE) || true
	kubectl delete namespace $(NAMESPACE) --ignore-not-found=true

.PHONY: all
all: deploy-app apply-prometheus-rule apply-playbook

.PHONY: help
help:
	@echo "Available targets:"
	@echo "  make all                  - Deploy app + rule + playbook"
	@echo "  make test-error           - Trigger simulated error"
	@echo "  make clean                - Clean up"