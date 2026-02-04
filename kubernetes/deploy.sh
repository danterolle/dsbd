#!/bin/bash

CLUSTER_NAME="flight-tracker"
SERVICES=("user-manager" "data-collector" "alert-system" "alert-notifier-system" "sla-breach-detector")
PF_PORTS=("5000:5000" "5001:5000" "5002:5000" "5003:5000" "5004:5000")

TIMEOUT_POD_READY=600
TIMEOUT_DEPLOYMENT=600
TIMEOUT_INGRESS=300

LOG_DIR="logs"
mkdir -p "$LOG_DIR"

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
    echo "  --ingress               Install NGINX Ingress Controller and enable Ingress access."
    echo ""
}

stop_port_forward() {
    echo "[*] Stopping existing port-forwarding processes..."
    PIDS=$(pgrep -f "kubectl port-forward svc/(user-manager|data-collector|alert-system|alert-notifier-system|sla-breach-detector)") || true
    if [ -n "$PIDS" ]; then
        echo "$PIDS" | xargs kill -9 2>/dev/null || true
        echo "[!] Port-forwarding stopped."
    else
        echo "[!] No existing port-forwarding processes found."
    fi
}

delete_cluster() {
    echo "[*] Deleting kind cluster '${CLUSTER_NAME}'..."
    kind delete cluster --name "${CLUSTER_NAME}"
    echo "[!] Done."
}

deploy() {
    mkdir -p "$LOG_DIR"
    LOG_FILE="$LOG_DIR/${CLUSTER_NAME}-$(date +%Y%m%d-%H%M%S).log"
    exec > >(tee -a "$LOG_FILE") 2>&1

    echo "==============================================="
    echo "[*] Deployment started at $(date)"
    echo "[*] Logging to: $LOG_FILE"
    echo "==============================================="
    echo ""

    START_PF=false
    INSTALL_INGRESS=false
    if [[ "$*" == *"--pf"* ]] || [[ "$*" == *"--port-forward"* ]]; then
        START_PF=true
    fi
    if [[ "$*" == *"--ingress"* ]]; then
        INSTALL_INGRESS=true
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
  kubeadmConfigPatches:
  - |
    kind: InitConfiguration
    nodeRegistration:
      kubeletExtraArgs:
        node-labels: "ingress-ready=true"
  extraPortMappings:
  # Prometheus NodePort
  - containerPort: 30090
    hostPort: 30090
    protocol: TCP
  # User Manager NodePort
  - containerPort: 30000
    hostPort: 30000
    protocol: TCP
  # Data Collector NodePort
  - containerPort: 30001
    hostPort: 30001
    protocol: TCP
  # Alert System NodePort
  - containerPort: 30002
    hostPort: 30002
    protocol: TCP
  # Alert Notifier System NodePort
  - containerPort: 30003
    hostPort: 30003
    protocol: TCP
  # SLA Breach Detector NodePort
  - containerPort: 30004
    hostPort: 30004
    protocol: TCP
  # HTTP for Ingress
  - containerPort: 80
    hostPort: 80
    protocol: TCP
  # HTTPS for Ingress
  - containerPort: 443
    hostPort: 443
    protocol: TCP
# Uncomment the following lines to enable a multi-node cluster (1 CP + 2 Workers)
# - role: worker
# - role: worker
EOF
    fi

    if [ "$INSTALL_INGRESS" = true ]; then
        echo "[+] Installing NGINX Ingress Controller..."
        kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml
        
        echo "[*] Waiting for Ingress Controller namespace to be ready..."
        sleep 5
        
        echo "[*] Waiting for Ingress Controller deployment..."
        until kubectl get deployment -n ingress-nginx ingress-nginx-controller &>/dev/null; do
            echo "    Waiting for ingress-nginx-controller deployment to be created..."
            sleep 3
        done
        
        echo "[*] Waiting for Ingress Controller pod to be ready..."
        kubectl wait --namespace ingress-nginx \
            --for=condition=ready pod \
            --selector=app.kubernetes.io/component=controller \
            --timeout=${TIMEOUT_INGRESS}s
    fi

    echo "[+] building Docker images..."
    docker build -t user-manager:latest ./microservices/user_manager
    docker build -t data-collector:latest ./microservices/data_collector
    docker build -t alert-system:latest ./microservices/alert_system
    docker build -t alert-notifier-system:latest ./microservices/alert_notifier_system
    docker build -t sla-breach-detector:latest ./microservices/sla_breach_detector

    echo "[+] copy the Docker images into the ${CLUSTER_NAME} cluster nodes"
    kind load docker-image user-manager:latest --name ${CLUSTER_NAME}
    kind load docker-image data-collector:latest --name ${CLUSTER_NAME}
    kind load docker-image alert-system:latest --name ${CLUSTER_NAME}
    kind load docker-image alert-notifier-system:latest --name ${CLUSTER_NAME}
    kind load docker-image sla-breach-detector:latest --name ${CLUSTER_NAME}

    echo "[+] applying k8s manifests..."
    kubectl apply -f kubernetes/

    echo "[*] waiting for deployments to be ready..."
    kubectl wait --for=condition=ready pod -l app=zookeeper --timeout=${TIMEOUT_POD_READY}s
    kubectl wait --for=condition=ready pod -l app=kafka --timeout=${TIMEOUT_POD_READY}s
    kubectl wait --for=condition=ready pod -l app=user-db --timeout=${TIMEOUT_POD_READY}s
    kubectl wait --for=condition=ready pod -l app=data-db --timeout=${TIMEOUT_POD_READY}s

    echo "[*] checking rollout status..."
    for svc in "${SERVICES[@]}"; do
        kubectl rollout status deployment/"$svc" --timeout=${TIMEOUT_DEPLOYMENT}s
    done
    kubectl rollout status deployment/prometheus --timeout=${TIMEOUT_DEPLOYMENT}s

    echo ""
    echo "==============================================="
    echo "[!] Deployment complete"
    echo "==============================================="
    echo ""
    echo "Prometheus UI: http://localhost:30090"
    echo "User Manager metrics: http://localhost:30000/metrics"

    echo ""
    echo "[+] Seeding database..."
    chmod +x kubernetes/seed.sh
    ./kubernetes/seed.sh
    echo "[!] Database seeding complete."

    if [ "$INSTALL_INGRESS" = true ]; then
        echo ""
        echo "Ingress enabled! Access services via:"
        echo "    - User Manager:   curl http://localhost/user-manager/ping"
        echo "    - Data Collector: curl http://localhost/data-collector/ping"
        echo "    - SLA Detector:   curl http://localhost/sla-detector/ping"
    fi

    if [ "$START_PF" = true ]; then
        stop_port_forward 
        echo "[+] Starting port-forwarding in background..."
        for i in "${!SERVICES[@]}"; do
            kubectl port-forward "svc/${SERVICES[$i]}" "${PF_PORTS[$i]}" > /dev/null 2>&1 &
        done
        echo "[!] Port-forwarding active. Use '$0 stop-pf' to stop them."
        echo "    - User Manager: http://localhost:5000"
        echo "    - Data Collector: http://localhost:5001"
        echo "    - Alert System: http://localhost:5002"
        echo "    - Alert Notifier: http://localhost:5003"
        echo "    - SLA Detector: http://localhost:5004"
    else
        if [ "$INSTALL_INGRESS" = false ]; then
            echo ""
            echo "To access services via direct port-forward, run with --pf"
        fi
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
        
        if [[ "$ACTION" == --* ]]; then
            deploy "$@"
        else
            echo "Error: Unknown action '$ACTION'"
            usage
            exit 1
        fi
        ;;
esac