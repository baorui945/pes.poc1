# Flask RCA Demo for Robusta

A demo application that simulates errors (DB failure, API timeout, validation) with structured logs, Prometheus metrics, and trace IDs — ideal for testing Robusta's observability and auto-remediation.

## Quick Start
```bash
make all
make test-error