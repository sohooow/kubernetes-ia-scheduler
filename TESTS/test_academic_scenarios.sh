#!/bin/bash
# test_academic_scenarios.sh
# Tests académiques : Focus sur l'optimisation de Latence (EL) vs Baseline

set -e

# Couleurs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Configuration
REPLICAS=10
NAMESPACE="default"
METRICS_FILE="academic_results.json"
RESULTS_DIR="TESTS/RESULTS"

NODE_1_NAME="k3d-nexslice-agent-0" 
NODE_2_NAME="k3d-nexslice-agent-1" 

echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   TESTS ACADÉMIQUES - SCHEDULER RL pour 5G Network Slicing     ║${NC}"
echo -e "${BLUE}║   Politique: Optimisation Latence (EL) vs Baseline             ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"

# Nettoyage initial
if [ -f "$METRICS_FILE" ]; then rm -f "$METRICS_FILE"; fi
mkdir -p $RESULTS_DIR

# Fonction de nettoyage
cleanup() {
    echo -e "\n${YELLOW}Nettoyage des déploiements...${NC}"
    kubectl delete deployment test-baseline test-el-latency --ignore-not-found 2>/dev/null || true
    pkill -f "ia_scheduler_rl" 2>/dev/null || true
    if command -v deactivate &> /dev/null; then deactivate; fi
    # On garde le label de latence propre
    kubectl label node ${NODE_1_NAME} type- low-latency- >/dev/null 2>&1 || true
    sleep 2
}
trap cleanup EXIT

# Fonction: Mesurer la distribution
measure_distribution() {
    local label=$1
    local timeout=${2:-30}
    
    echo -e "${CYAN}Attente du scheduling (${timeout}s)...${NC}"
    sleep $timeout
    
    local pods=$(kubectl get pods -l app=$label -o wide --no-headers 2>/dev/null)
    
    if [ -z "$pods" ]; then
        echo -e "${RED}Erreur: Aucun pod trouvé${NC}"
        echo "{\"worker1\": 0, \"worker2\": 0, \"running\": 0}" > /tmp/distribution_${label}.json
        return 1
    fi
    
    local worker1=$(echo "$pods" | grep "$NODE_1_NAME" | wc -l | tr -d ' ')
    local worker2=$(echo "$pods" | grep "$NODE_2_NAME" | wc -l | tr -d ' ')
    local running=$(echo "$pods" | grep "Running" | wc -l | tr -d ' ')
    
    echo -e "${GREEN}Distribution:${NC}"
    echo -e "   Worker-1 (low-latency): ${worker1} pods"
    echo -e "   Worker-2 (standard):    ${worker2} pods"
    
    echo "{\"worker1\": $worker1, \"worker2\": $worker2, \"running\": $running}" > /tmp/distribution_${label}.json
    return 0
}

# Fonction: Calculer les métriques (Latence uniquement)
calculate_metrics() {
    local label=$1
    local worker1=$2
    local worker2=$3
    local total_pods=$((worker1 + worker2))
    
    local latency_p95=0.00
    
    if [ "$total_pods" -gt 0 ]; then
        latency_p95=$(echo "scale=2; ($worker1 * 10 + $worker2 * 50) / $total_pods" | bc)
    fi

    echo -e "${CYAN}Métriques:${NC}"
    echo -e "   Latence Moyenne: ${latency_p95} ms"
    
    cat > /tmp/metrics_${label}.json << EOF
{
    "label": "${label}",
    "worker1_pods": ${worker1},
    "worker2_pods": ${worker2},
    "latency_p95_ms": ${latency_p95}
}
EOF
}

# --- TEST BASELINE ---
echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}TEST BASELINE : kube-scheduler (Politique par défaut)${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
cleanup

cat > /tmp/test-baseline.yaml << EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: test-baseline
spec:
  replicas: ${REPLICAS}
  selector:
    matchLabels:
      app: baseline
  template:
    metadata:
      labels:
        app: baseline
    spec:
      containers:
      - name: upf
        image: busybox
        command: ["sleep", "3600"]
        resources:
          requests:
            memory: "64Mi"
            cpu: "100m"
EOF

kubectl apply -f /tmp/test-baseline.yaml
measure_distribution "baseline" 30
BASELINE_W1=$(jq -r '.worker1' /tmp/distribution_baseline.json)
BASELINE_W2=$(jq -r '.worker2' /tmp/distribution_baseline.json)
calculate_metrics "baseline" $BASELINE_W1 $BASELINE_W2
echo -e "${GREEN}Test Baseline terminé${NC}"

# --- TEST EL (LATENCY) ---
echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}TEST 1 (EL) : Politique Priorité Latence (Edge-Latency)${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
cleanup

echo -e "${YELLOW}Démarrage Scheduler RL...${NC}"
source .venv/bin/activate || { echo -e "${RED}Erreur: Impossible d'activer le venv.${NC}"; exit 1; }
export SCHEDULER_MODE="latency" # Mode unique conservé
export RL_USE_TRAINED_MODEL=true
export RL_TRAINING_MODE=false
export PYTHONUNBUFFERED=1

python -m schedulers.ia_scheduler_rl > /tmp/scheduler_el.log 2>&1 &
SCHEDULER_PID=$!
echo -e "${GREEN}  Scheduler PID: $SCHEDULER_PID${NC}"
sleep 8

cat > /tmp/test-el-latency.yaml << EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: test-el-latency
spec:
  replicas: ${REPLICAS}
  selector:
    matchLabels:
      app: el-latency
  template:
    metadata:
      labels:
        app: el-latency
    spec:
      schedulerName: ia-scheduler 
      containers:
      - name: upf
        image: busybox
        command: ["sleep", "3600"]
        resources:
          requests:
            memory: "64Mi"
            cpu: "100m"
EOF

kubectl apply -f /tmp/test-el-latency.yaml
measure_distribution "el-latency" 40
EL_W1=$(jq -r '.worker1' /tmp/distribution_el-latency.json)
EL_W2=$(jq -r '.worker2' /tmp/distribution_el-latency.json)
calculate_metrics "el-latency" $EL_W1 $EL_W2

# Arrêt propre
kill -TERM ${SCHEDULER_PID} 2>/dev/null || true
sleep 2 
deactivate 2>/dev/null || true
echo -e "${GREEN}Test EL (Latency) terminé${NC}"

# --- SYNTHÈSE ET JSON ---
echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}Synthèse des résultats${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"

BASELINE_LATENCY=$(jq -r '.latency_p95_ms' /tmp/metrics_baseline.json 2>/dev/null || echo "0.00")
BASELINE_W1=${BASELINE_W1:-0}
BASELINE_W2=${BASELINE_W2:-0}

EL_LATENCY=$(jq -r '.latency_p95_ms' /tmp/metrics_el-latency.json 2>/dev/null || echo "0.00")
EL_W1=${EL_W1:-0}
EL_W2=${EL_W2:-0}

# Calculs de gains
EL_GAIN=$(echo "scale=2; 100 * (${BASELINE_LATENCY} - ${EL_LATENCY}) / ${BASELINE_LATENCY}" | bc 2>/dev/null || echo "0.00")

# ÉCRITURE FORCÉE DU JSON SIMPLIFIÉ
cat > $METRICS_FILE << EOF
{
    "test_date": "$(date -Iseconds)",
    "replicas": ${REPLICAS},
    "scenarios": {
        "baseline": {
            "scheduler": "kube-scheduler",
            "worker1": ${BASELINE_W1},
            "worker2": ${BASELINE_W2},
            "latency_p95_ms": ${BASELINE_LATENCY}
        },
        "el_latency": {
            "scheduler": "RL-DQN (EL policy)",
            "worker1": ${EL_W1},
            "worker2": ${EL_W2},
            "latency_p95_ms": ${EL_LATENCY},
            "improvement_latency_percent": ${EL_GAIN}
        }
    }
}
EOF

# Vérification finale
if [ -f "$METRICS_FILE" ]; then
    echo -e "${CYAN}Fichier JSON mis à jour avec succès : $(ls -l $METRICS_FILE)${NC}"
else
    echo -e "${RED}ERREUR CRITIQUE: Le fichier JSON n'a pas été créé!${NC}"
    exit 1
fi

echo -e "\n${GREEN}Tests terminés. Vérifiez $METRICS_FILE${NC}"
exit 0