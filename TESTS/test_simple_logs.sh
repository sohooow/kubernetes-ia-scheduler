#!/bin/bash

# Test simple avec logs garantis

set -e

echo "🧪 Test simple du scheduler RL avec logs..."

# Nettoyer
kubectl delete deployment stress-load test-lb-simple --ignore-not-found 2>/dev/null || true
pkill -f "ia_scheduler" 2>/dev/null || true
sleep 2

# Créer charge de stress sur worker-1
echo "💪 Application charge de stress..."
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: stress-load
spec:
  replicas: 7
  selector:
    matchLabels:
      app: stress
  template:
    metadata:
      labels:
        app: stress
    spec:
      nodeSelector:
        kubernetes.io/hostname: k3d-nexslice-worker-1-0
      containers:
      - name: stress
        image: busybox
        command: ["sh", "-c", "while true; do :; done"]
        resources:
          requests:
            cpu: "1000m"
            memory: "256Mi"
EOF

sleep 15
echo "✅ Charge de stress appliquée"

# Démarrer scheduler avec logs
echo "🚀 Démarrage scheduler RL..."

cd /Users/sonia/kubernetes-ia-scheduler
source .venv/bin/activate

export RL_USE_TRAINED_MODEL=true
export RL_TRAINING_MODE=false
export RL_DEBUG=true
export PYTHONUNBUFFERED=1

# Lancer scheduler en arrière-plan avec redirection explicite
python -m schedulers.ia_scheduler_rl > /tmp/scheduler_test.log 2>&1 &
SCHEDULER_PID=$!
echo "Scheduler PID: $SCHEDULER_PID"

# Attendre que le scheduler démarre
sleep 5

# Vérifier que le scheduler fonctionne
if ps -p $SCHEDULER_PID > /dev/null; then
    echo "✅ Scheduler est en cours d'exécution"
else
    echo "❌ Scheduler s'est arrêté"
    cat /tmp/scheduler_test.log
    exit 1
fi

# Créer un pod de test
echo "📦 Création d'un pod de test..."
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: test-lb-simple
spec:
  replicas: 3
  selector:
    matchLabels:
      app: test-lb
  template:
    metadata:
      labels:
        app: test-lb
    spec:
      schedulerName: custom-ia-scheduler-rl
      containers:
      - name: test
        image: busybox
        command: ["sleep", "3600"]
        resources:
          requests:
            cpu: "100m"
            memory: "64Mi"
EOF

echo "⏳ Attente du scheduling (30s)..."
sleep 30

# Vérifier le résultat
echo "📊 Résultats du scheduling:"
kubectl get pods -l app=test-lb -o wide --no-headers | while read line; do
    node=$(echo $line | awk '{print $7}')
    echo "  Pod placé sur: $node"
done

# Compter par nœud
worker1_count=$(kubectl get pods -l app=test-lb -o wide --no-headers | grep "worker-1" | wc -l)
worker2_count=$(kubectl get pods -l app=test-lb -o wide --no-headers | grep "worker-2" | wc -l)

echo ""
echo "Distribution finale:"
echo "  Worker-1 (saturé à 70% CPU): $worker1_count pods"
echo "  Worker-2 (libre): $worker2_count pods"

# Arrêter le scheduler
kill $SCHEDULER_PID 2>/dev/null || true
sleep 2

# Afficher les logs
echo ""
echo "📋 LOGS DU SCHEDULER:"
echo "===================="
cat /tmp/scheduler_test.log

# Nettoyer
echo ""
echo "🧹 Nettoyage..."
kubectl delete deployment stress-load test-lb-simple --ignore-not-found 2>/dev/null || true

echo "✅ Test terminé"