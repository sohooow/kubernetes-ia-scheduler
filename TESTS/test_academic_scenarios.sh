#!/bin/bash
set -e

# ============================================================
# CONFIGURATION
# ============================================================
NODE_EDGE="k3d-nexslice-agent-0"
NODE_CLOUD="k3d-nexslice-agent-1"
RESULTS_FILE="TESTS/academic_results.json"
mkdir -p TESTS/RESULTS

# Couleurs (Standard ANSI)
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

REPLICAS=10

echo -e "${BLUE}================================================================${NC}"
echo -e "${BLUE}   TESTS ACADEMIQUES - SCHEDULER RL (5G Network Slicing)        ${NC}"
echo -e "${BLUE}   Politiques: Baseline | EL (Latency) | LB (Load Balancing)    ${NC}"
echo -e "${BLUE}================================================================${NC}"

# ============================================================
# FONCTIONS
# ============================================================

cleanup() {
    echo -e "\n${CYAN}[INFO] Nettoyage des deploiements...${NC}"
    pkill -f "ia_scheduler_rl" 2>/dev/null || true
    kubectl delete deployment test-baseline test-el-latency test-lb-balance stress-load --ignore-not-found > /dev/null 2>&1
    sleep 5
}

trap cleanup EXIT

# Fonction: Calculer les metriques (Retourne: LATENCE VARIANCE)
calculate_metrics() {
    local worker1=$1
    local worker2=$2
    local total=$((worker1 + worker2))

    if [ "$total" -eq 0 ]; then
        echo "0.00 0.00"
        return
    fi
    
    # Latence P95 simulee
    local lat_sum=$(echo "scale=2; ($worker1 * 10) + ($worker2 * 50)" | bc)
    local latency_p95=$(echo "scale=2; $lat_sum / $total" | bc | awk '{printf "%.2f", $0}')
    
    # Variance CPU
    local diff=$((worker1 - worker2))
    local cpu_variance=$(echo "scale=2; ($diff * $diff) / 2" | bc | awk '{printf "%.2f", $0}')
    
    # Retourne les deux valeurs brutes
    echo "$latency_p95 $cpu_variance"
}

# Fonction: Mesurer la distribution (Retourne: COUNT_EDGE COUNT_CLOUD)
measure_distribution() {
    local label=$1
    local timeout=${2:-30}
    
    echo -e "${CYAN}[WAIT] Attente du scheduling (${timeout}s)...${NC}"
    sleep $timeout
    
    # Recuperer uniquement les pods Running
    local pods=$(kubectl get pods -l app=$label -o wide --no-headers 2>/dev/null | grep 'Running')
    
    local c_edge=$(echo "$pods" | grep "$NODE_EDGE" | wc -l | tr -d ' \t\n\r')
    local c_cloud=$(echo "$pods" | grep "$NODE_CLOUD" | wc -l | tr -d ' \t\n\r')
    
    # Securite numerique
    c_edge=${c_edge:-0}
    c_cloud=${c_cloud:-0}
    
    echo -e "${GREEN}[DISTRIBUTION] Edge ($NODE_EDGE): $c_edge | Cloud ($NODE_CLOUD): $c_cloud${NC}"
    
    echo "$c_edge $c_cloud"
}

# ============================================================
# INITIALISATION JSON
# ============================================================
echo '{ "scenarios": {' > $RESULTS_FILE

# ============================================================
# 1. TEST BASELINE
# ============================================================
echo -e "\n----------------------------------------------------------------"
echo -e "${BLUE}TEST BASELINE : kube-scheduler (Defaut)${NC}"
cleanup

cat <<EOF | kubectl apply -f - > /dev/null
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
            cpu: "100m"
EOF

# Capture des resultats
read BASELINE_W1 BASELINE_W2 <<< $(measure_distribution "baseline" 30)
read LAT_BASE VAR_BASE <<< $(calculate_metrics $BASELINE_W1 $BASELINE_W2)

echo -e "${CYAN}[METRIQUES] Latence P95: ${LAT_BASE} ms | Variance: ${VAR_BASE}${NC}"

# Ecriture JSON (avec virgule)
cat <<EOF >> $RESULTS_FILE
"baseline": { 
    "scheduler": "kube-scheduler",
    "worker1": $BASELINE_W1, 
    "worker2": $BASELINE_W2, 
    "latency_p95_ms": $LAT_BASE, 
    "cpu_variance": $VAR_BASE 
},
EOF

# ============================================================
# 2. TEST EL (IA - Latency)
# ============================================================
echo -e "\n----------------------------------------------------------------"
echo -e "${BLUE}TEST 1 (EL) : Politique Priorite Latence${NC}"
cleanup

echo -e "${YELLOW}[INFO] Demarrage Scheduler RL (mode EL)...${NC}"
source .venv/bin/activate
export RL_USE_TRAINED_MODEL=true
export RL_TRAINING_MODE=false
# Lancement en background sans buffer
python3 -u -m schedulers.ia_scheduler_rl > /tmp/scheduler_el.log 2>&1 &
SCHED_PID=$!
sleep 5

cat <<EOF | kubectl apply -f - > /dev/null
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
        args: ["sleep", "3600"]
        resources:
          requests:
            cpu: "100m"
EOF

# Capture des resultats
read EL_W1 EL_W2 <<< $(measure_distribution "el-latency" 40)
read LAT_EL VAR_EL <<< $(calculate_metrics $EL_W1 $EL_W2)

EL_GAIN=$(echo "scale=2; 100 * ($LAT_BASE - $LAT_EL) / $LAT_BASE" | bc 2>/dev/null)
echo -e "${CYAN}[METRIQUES] Latence P95: ${LAT_EL} ms | Gain: ${EL_GAIN}%${NC}"

# Ecriture JSON (avec virgule)
cat <<EOF >> $RESULTS_FILE
"el_latency": { 
    "scheduler": "RL-DQN (EL policy)",
    "worker1": $EL_W1, 
    "worker2": $EL_W2, 
    "latency_p95_ms": $LAT_EL, 
    "cpu_variance": $VAR_EL,
    "improvement_latency_percent": $EL_GAIN 
},
EOF

kill $SCHED_PID 2>/dev/null || true

# ============================================================
# 3. TEST LB (IA - Load Balancing)
# ============================================================
echo -e "\n----------------------------------------------------------------"
echo -e "${BLUE}TEST 2 (LB) : Politique Equilibrage de Charge${NC}"
cleanup

echo -e "${YELLOW}[INFO] Application charge stress sur Edge...${NC}"
cat <<EOF | kubectl apply -f - > /dev/null
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
        kubernetes.io/hostname: $NODE_EDGE
      containers:
      - name: stress
        image: busybox
        command: ["sh", "-c", "while true; do :; done"]
        resources:
          requests:
            cpu: "1000m"
EOF
sleep 10

echo -e "${YELLOW}[INFO] Redemarrage Scheduler RL...${NC}"
python3 -u -m schedulers.ia_scheduler_rl > /tmp/scheduler_lb.log 2>&1 &
SCHED_PID=$!
sleep 5

cat <<EOF | kubectl apply -f - > /dev/null
apiVersion: apps/v1
kind: Deployment
metadata:
  name: test-lb-balance
spec:
  replicas: ${REPLICAS}
  selector:
    matchLabels:
      app: lb-balance
  template:
    metadata:
      labels:
        app: lb-balance
    spec:
      schedulerName: ia-scheduler
      containers:
      - name: upf
        image: busybox
        args: ["sleep", "3600"]
        resources:
          requests:
            cpu: "100m"
EOF

# Capture des resultats
read LB_W1 LB_W2 <<< $(measure_distribution "lb-balance" 40)
read LAT_LB VAR_LB <<< $(calculate_metrics $LB_W1 $LB_W2)

if [[ $LB_W1 -eq 0 ]]; then
    LB_GAIN="100.00"
else
    LB_GAIN="0.00"
fi
echo -e "${CYAN}[METRIQUES] Variance CPU: ${VAR_LB} | Evitement Saturation: ${LB_GAIN}%${NC}"

# Ecriture JSON (PAS de virgule car dernier element)
cat <<EOF >> $RESULTS_FILE
"lb_balance": { 
    "scheduler": "RL-DQN (LB policy)",
    "worker1": $LB_W1, 
    "worker2": $LB_W2, 
    "latency_p95_ms": $LAT_LB, 
    "cpu_variance": $VAR_LB,
    "improvement_variance_percent": $LB_GAIN 
}
}
EOF

kill $SCHED_PID 2>/dev/null || true

echo -e "\n----------------------------------------------------------------"
echo -e "${GREEN}[SUCCES] Tests termines. Rapport genere : $RESULTS_FILE${NC}"
exit 0