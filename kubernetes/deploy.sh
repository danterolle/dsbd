#!/bin/bash

CLUSTER_NAME="flight-tracker"
SERVICES=("user-manager" "data-collector" "alert-system" "alert-notifier-system")
PF_PORTS=("5000:5000" "5001:5000" "5002:5000" "5003:5000")

set -euo pipefail

usage() {
    echo "Usage: $0 [ACTION] [OPTIONS]"
    echo ""
    echo "Actions:"
    echo "  up (default)    Create cluster, build images, and deploy."
    echo "  down            Delete the kind cluster."
    echo "  stop-pf         Stop all active port-forwarding processes."
    echo ""
    echo "Options for 'up':"
    echo "  --pf, --port-forward    Automatically start port-forwarding after deployment."
    echo ""
}

stop_port_forward() {
    echo "[*] Stopping existing port-forwarding processes..."
    # We use pkill with a specific pattern to avoid killing other unrelated kubectl commands
    pgrep -f "kubectl port-forward svc/(user-manager|data-collector|alert-system|alert-notifier-system)" | xargs kill -9 2>/dev/null
    echo "[!] Port-forwarding stopped."
}

delete_cluster() {
    echo "[*] Deleting kind cluster '${CLUSTER_NAME}'..."
    kind delete cluster --name "${CLUSTER_NAME}"
    echo "[!] Done."
}

deploy() {
    START_PF=false
    if [[ "$*" == *"--pf"* ]] || [[ "$*" == *"--port-forward"* ]]; then
        START_PF=true
    fi

    if kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
        echo "[!] kind cluster '${CLUSTER_NAME}' already exists."
    else
        echo "[+] creating kind cluster '${CLUSTER_NAME}'..."
        cat <<EOF | kind create cluster --name ${CLUSTER_NAME} --config=-
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  extraPortMappings:
  - containerPort: 30090
    hostPort: 30090
    protocol: TCP
  - containerPort: 30000
    hostPort: 30000
    protocol: TCP
EOF
    fi

    echo "[+] building Docker images..."
    docker build -t user-manager:latest ./microservices/user_manager
    docker build -t data-collector:latest ./microservices/data_collector
    docker build -t alert-system:latest ./microservices/alert_system
    docker build -t alert-notifier-system:latest ./microservices/alert_notifier_system

    echo "[+] copy the Docker images into the ${CLUSTER_NAME} cluster nodes"
    kind load docker-image user-manager:latest --name ${CLUSTER_NAME}
    kind load docker-image data-collector:latest --name ${CLUSTER_NAME}
    kind load docker-image alert-system:latest --name ${CLUSTER_NAME}
    kind load docker-image alert-notifier-system:latest --name ${CLUSTER_NAME}

    echo "[+] applying k8s manifests..."
    kubectl apply -f kubernetes/

    echo "[*] waiting for deployments to be ready..."
    kubectl wait --for=condition=ready pod -l app=zookeeper --timeout=300s
    kubectl wait --for=condition=ready pod -l app=kafka --timeout=300s
    kubectl wait --for=condition=ready pod -l app=user-db --timeout=300s
    kubectl wait --for=condition=ready pod -l app=data-db --timeout=300s

    echo "[*] checking rollout status..."
    for svc in "${SERVICES[@]}"; do
        kubectl rollout status deployment/"$svc" --timeout=300s
    done
    kubectl rollout status deployment/prometheus --timeout=300s

    echo ""
    echo "==============================================="
    echo "[!] Deployment complete"
    echo "==============================================="
    echo ""
    echo "Prometheus UI: http://localhost:30090"
    echo "User Manager metrics: http://localhost:30000/metrics"

    if [ "$START_PF" = true ]; then
        stop_port_forward # Clean up old ones first!
        echo "[+] Starting port-forwarding in background..."
        for i in "${!SERVICES[@]}"; do
            kubectl port-forward "svc/${SERVICES[$i]}" "${PF_PORTS[$i]}" > /dev/null 2>&1 &
        done
        echo "[!] Port-forwarding active. Use '$0 stop-pf' to stop them."
        echo "    - User Manager: http://localhost:5000"
        echo "    - Data Collector: http://localhost:5001"
        echo "    - Alert System: http://localhost:5002"
        echo "    - Alert Notifier: http://localhost:5003"
    else
        echo ""
        echo "To access services via direct port-forward, run with --pf or use:"
        echo "  kubectl port-forward svc/user-manager 5000:5000"
    fi
    echo ""
}

ACTION=${1:-"up"}

case $ACTION in
    up)
        deploy "$@"
        ;;
    down)
        if kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
            stop_port_forward
            delete_cluster
        else
            echo "[!] ${CLUSTER_NAME} cluster does not exist. Nothing to delete."
        fi
        ;;
    stop-pf)
        stop_port_forward
        ;;
    --help|-h)
        usage
        ;;
    *)
        # Default to deploy if first arg is a flag or empty
        if [[ "$ACTION" == --* ]]; then
            deploy "$@"
        else
            echo "Error: Unknown action '$ACTION'"
            usage
            exit 1
        fi
        ;;
esac