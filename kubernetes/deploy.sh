#!/bin/bash

set -euo pipefail

# We use kind (Kubernetes in Docker) to provide a local k8s cluster.
# Kind runs the cluster inside Docker containers.

# Use cURL or package managers to install kind, for example: brew install kind (macOS)

CLUSTER_NAME="flight-tracker"

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

echo "[*] check the pods status..."
kubectl rollout status deployment/prometheus --timeout=300s
kubectl rollout status deployment/user-manager --timeout=300s
kubectl rollout status deployment/data-collector --timeout=300s
kubectl rollout status deployment/alert-system --timeout=300s
kubectl rollout status deployment/alert-notifier-system --timeout=300s

echo ""
echo "==============================================="
echo "[!] Deployment complete"
echo "==============================================="
echo ""
echo "Prometheus UI: http://localhost:30090"
echo "User Manager metrics: http://localhost:30000/metrics"
echo ""
echo "To access services via direct port-forward (bypass Nginx):"
echo "  kubectl port-forward svc/user-manager 5000:5000"
echo "  kubectl port-forward svc/data-collector 5001:5000"
echo "  kubectl port-forward svc/alert-system 5002:5000"
echo "  kubectl port-forward svc/alert-notifier-system 5003:5000"
echo ""
echo "To delete the cluster:"
echo "  kind delete cluster --name ${CLUSTER_NAME}"
echo ""