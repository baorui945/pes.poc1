import logging
import json
import uuid
import random
import time
import traceback
from flask import Flask, request, jsonify
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST

# ===== 配置结构化日志 =====
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("metric-sim")
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('%(message)s'))
logger.handlers = [handler]

# ===== Prometheus 指标定义 =====
REQUEST_COUNT = Counter('http_requests_total', 'Total HTTP requests', ['method', 'endpoint', 'status'])
REQUEST_LATENCY = Histogram('http_request_duration_seconds', 'Request duration', ['endpoint'])
ERROR_COUNT = Counter('app_errors_total', 'Application errors', ['error_type', 'endpoint'])
DB_CONNECTION_GAUGE = Gauge('db_active_connections', 'Simulated DB connections')
THIRD_PARTY_FAILURE_GAUGE = Gauge('third_party_api_failures', 'Count of simulated third-party failures')

app = Flask(__name__)

db_connected = True
third_party_api_available = True

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

    log_data = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "trace_id": getattr(request, 'trace_id', 'unknown'),
        "method": request.method,
        "url": request.url,
        "status": response.status_code,
        "duration_sec": round(duration, 3),
        "user_agent": request.headers.get('User-Agent', 'unknown')
    }
    logger.info(json.dumps(log_data))
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
    details = {}
    if not db_connected:
        status = "degraded"
        details["db"] = "Connection lost"
    if not third_party_api_available:
        status = "degraded"
        details["third_party_api"] = "Service unreachable"

    return jsonify({"status": status, "details": details})

@app.route('/process_order')
def process_order():
    trace_id = request.trace_id
    order_id = request.args.get('order_id', 'unknown')
    simulate_error = request.args.get('error', None)

    try:
        if not order_id or order_id == "invalid":
            raise ValueError("Invalid order_id")

        if not db_connected or simulate_error == "db":
            ERROR_COUNT.labels(error_type="DatabaseConnectionError", endpoint="process_order").inc()
            raise ConnectionError("Failed to connect to database")

        if not third_party_api_available or simulate_error == "api_timeout":
            ERROR_COUNT.labels(error_type="ThirdPartyTimeout", endpoint="process_order").inc()
            raise TimeoutError("Third-party API timeout after 5s")

        time.sleep(random.uniform(0.1, 0.5))

        return jsonify({
            "trace_id": trace_id,
            "order_id": order_id,
            "status": "processed"
        })

    except ValueError as e:
        ERROR_COUNT.labels(error_type="ValidationError", endpoint="process_order").inc()
        logger.error(json.dumps({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "level": "error",
            "trace_id": trace_id,
            "error_type": "ValidationError",
            "message": str(e),
            "order_id": order_id,
            "stack_trace": traceback.format_exc()
        }))
        return jsonify({"error": "Validation failed", "detail": str(e)}), 400

    except (ConnectionError, TimeoutError) as e:
        logger.error(json.dumps({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "level": "error",
            "trace_id": trace_id,
            "error_type": type(e).__name__,
            "message": str(e),
            "order_id": order_id,
            "stack_trace": traceback.format_exc()
        }))
        return jsonify({"error": "Service unavailable", "detail": str(e)}), 503

    except Exception as e:
        ERROR_COUNT.labels(error_type="UnexpectedError", endpoint="process_order").inc()
        logger.error(json.dumps({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "level": "critical",
            "trace_id": trace_id,
            "error_type": "UnexpectedError",
            "message": str(e),
            "order_id": order_id,
            "stack_trace": traceback.format_exc()
        }))
        return jsonify({"error": "Internal server error"}), 500

@app.route('/metrics')
def metrics():
    return generate_latest(), 200, {'Content-Type': CONTENT_TYPE_LATEST}

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)