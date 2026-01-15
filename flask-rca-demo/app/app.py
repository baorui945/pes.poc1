import uuid
import random
import time
from flask import Flask, request, jsonify
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST

# ===== 尝试导入 kubernetes 客户端 =====
try:
    from kubernetes import client, config
    from kubernetes.client.rest import ApiException
    K8S_AVAILABLE = True
except ImportError:
    K8S_AVAILABLE = False

app = Flask(__name__)

# ===== Prometheus 指标（带上下文标签）=====
REQUEST_COUNT = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status']
)
REQUEST_LATENCY = Histogram(
    'http_request_duration_seconds',
    'Request duration',
    ['endpoint']
)
ERROR_COUNT = Counter(
    'app_errors_total',
    'Application errors with context',
    ['error_type', 'endpoint', 'order_id', 'trace_id']
)
DB_CONNECTION_GAUGE = Gauge('db_active_connections', 'Simulated DB connections')
THIRD_PARTY_FAILURE_GAUGE = Gauge('third_party_api_failures', 'Third-party API status')

# 全局依赖状态
db_connected = True
third_party_api_available = True

# 初始化 K8s 客户端（in-cluster）
if K8S_AVAILABLE:
    try:
        config.load_incluster_config()
        v1 = client.CoreV1Api()
        with open("/var/run/secrets/kubernetes.io/serviceaccount/namespace", "r") as f:
            NAMESPACE = f.read().strip()
        with open("/etc/hostname", "r") as f:
            POD_NAME = f.read().strip()
    except Exception:
        K8S_AVAILABLE = False

def emit_k8s_event(reason: str, message: str, event_type: str = "Warning"):
    """在当前 Pod 上创建 Kubernetes Event"""
    if not K8S_AVAILABLE:
        return
    try:
        event = client.V1Event(
            metadata=client.V1ObjectMeta(generate_name=f"{POD_NAME}-{reason.lower()}-"),
            involved_object=client.V1ObjectReference(
                kind="Pod",
                name=POD_NAME,
                namespace=NAMESPACE,
                api_version="v1"
            ),
            reason=reason,
            message=message,
            type=event_type,
            first_timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            last_timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            action="Processing",
            reporting_component="flask-rca-demo",
            reporting_instance=POD_NAME
        )
        v1.create_namespaced_event(namespace=NAMESPACE, body=event)
    except Exception:
        pass  # 安静失败

@app.before_request
def before_request():
    request.start_time = time.time()
    request.trace_id = str(uuid.uuid4())

@app.after_request
def after_request(response):
    duration = time.time() - request.start_time
    REQUEST_COUNT.labels(
        method=request.method,
        endpoint=request.endpoint or "unknown",
        status=str(response.status_code)
    ).inc()
    if hasattr(request, 'endpoint'):
        REQUEST_LATENCY.labels(endpoint=request.endpoint).observe(duration)
    return response

@app.route('/health')
def health():
    global db_connected, third_party_api_available
    if random.random() < 0.1:
        db_connected = not db_connected
    if random.random() < 0.05:
        third_party_api_available = not third_party_api_available

    DB_CONNECTION_GAUGE.set(5 if db_connected else 0)
    THIRD_PARTY_FAILURE_GAUGE.set(0 if third_party_api_available else 1)

    status = "healthy"
    if not db_connected or not third_party_api_available:
        status = "degraded"
    return jsonify({"status": status})

@app.route('/process_order')
def process_order():
    trace_id = request.trace_id
    order_id = request.args.get('order_id', 'unknown')
    simulate_error = request.args.get('error', None)

    try:
        if not order_id or order_id == "invalid":
            error_type = "ValidationError"
            ERROR_COUNT.labels(
                error_type=error_type,
                endpoint="process_order",
                order_id=order_id,
                trace_id=trace_id
            ).inc()
            emit_k8s_event("ValidationError", f"Invalid order_id: {order_id}")
            return jsonify({"error": "Validation failed"}), 400

        if not db_connected or simulate_error == "db":
            error_type = "DatabaseConnectionError"
            ERROR_COUNT.labels(
                error_type=error_type,
                endpoint="process_order",
                order_id=order_id,
                trace_id=trace_id
            ).inc()
            emit_k8s_event("DatabaseConnectionError", "Failed to connect to database")
            return jsonify({"error": "Service unavailable"}), 503

        if not third_party_api_available or simulate_error == "api_timeout":
            error_type = "ThirdPartyTimeout"
            ERROR_COUNT.labels(
                error_type=error_type,
                endpoint="process_order",
                order_id=order_id,
                trace_id=trace_id
            ).inc()
            emit_k8s_event("ThirdPartyTimeout", "Third-party API timeout")
            return jsonify({"error": "Service unavailable"}), 503

        time.sleep(random.uniform(0.1, 0.5))
        return jsonify({"trace_id": trace_id, "order_id": order_id, "status": "processed"})

    except Exception:
        error_type = "UnexpectedError"
        ERROR_COUNT.labels(
            error_type=error_type,
            endpoint="process_order",
            order_id=order_id,
            trace_id=trace_id
        ).inc()
        emit_k8s_event("UnexpectedError", "Unhandled exception in process_order")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/metrics')
def metrics():
    return generate_latest(), 200, {'Content-Type': CONTENT_TYPE_LATEST}

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)