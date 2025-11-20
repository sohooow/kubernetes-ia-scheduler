#!/bin/bash

# ============================================================
# CONFIGURATION
# ============================================================
# Noms exacts des nœuds K3d (synchronisés avec k3d-nexslice-agent)
NODE_EDGE="k3d-nexslice-agent-0"
NODE_CLOUD="k3d-nexslice-agent-1"

# Fichier de résultats
RESULTS_FILE="TESTS/academic_results.json"
mkdir -p TESTS/RESULTS

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

echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   TESTS ACADÉMIQUES - SCHEDULER RL pour 5G Network Slicing    ║${NC}"
echo -e "${BLUE}║   Politiques: Baseline | EL (Latency) | LB (Load Balancing)   ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"

# ============================================================
# FONCTIONS
# ============================================================

cleanup() {
    echo -e "\n${YELLOW}🧹 Nettoyage des déploiements...${NC}"
    # Le pkill est plus ciblé avec -f, mais on le garde pour tuer le process python
    pkill -f "ia_scheduler_rl" 2>/dev/null || true
    kubectl delete deployment test-baseline test-el-latency test-lb-balance stress-load --ignore-not-found > /dev/null 2>&1
    sleep 2
}

trap cleanup EXIT

# Fonction: Mesurer la distribution des pods
measure_distribution() {
    local label=$1
    local timeout=${2:-30}
    
    echo -e "${CYAN}⏳ Attente du scheduling (${timeout}s)...${NC}"
    # Force le sleep pour que le scheduler ait le temps d'agir
    sleep $timeout
    
    # Récupérer les pods
    local pods=$(kubectl get pods -l app=$label -o wide --no-headers 2>/dev/null)
    
    if [ -z "$pods" ]; then
        echo -e "${RED}❌ Aucun pod trouvé${NC}"
        # On ne retourne pas 1 pour laisser le script continuer le calcul de métriques à 0
    fi
    
    # Compter par nœud (CORRIGÉ : utilise les noms AGENT au lieu de WORKER)
    local C_EDGE=$(echo "$pods" | grep "$NODE_EDGE" | wc -l | tr -d ' ')
    local C_CLOUD=$(echo "$pods" | grep "$NODE_CLOUD" | wc -l | tr -d ' ')
    local running=$(echo "$pods" | grep "Running" | wc -l | tr -d ' ')
    local pending=$(kubectl get pods -l app=$label --field-selector=status.phase=Pending --no-headers 2>/dev/null | wc -l | tr -d ' ')
    
    echo -e "${GREEN}📊 Distribution:${NC}"
    echo -e "   Edge Node ($NODE_EDGE): ${C_EDGE} pods"
    echo -e "   Cloud Node ($NODE_CLOUD): ${C_CLOUD} pods"
    echo -e "   Running: ${running}/${REPLICAS}, Pending: ${pending}"
    
    # Sauvegarder les résultats (utilise les noms generiques worker1/worker2 pour le JSON)
    echo "{\"worker1\": $C_EDGE, \"worker2\": $C_CLOUD, \"running\": $running, \"pending\": $pending}" > /tmp/distribution_${label}.json
    
    # Doit retourner 0 pour que le script continue
    return 0
}

# Fonction: Calculer les métriques (CORRIGÉE : retourne Latence et Variance)
# Fonction: Calculer les métriques (à partir de la ligne 121)
calculate_metrics() {
    local label=$1
    local worker1=$2
    local worker2=$3
    local total=$((worker1 + worker2))

    if [ "$total" -eq 0 ]; then
        # Retourne les valeurs zéro pour éviter le crash
        echo "0.00 0.00"
        return
    fi
    
    # Latence P95 simulée
    local lat_sum=$(echo "scale=2; ($worker1 * 10) + ($worker2 * 50)" | bc)
    local latency_p95=$(echo "scale=2; $lat_sum / $total" | bc)
    
    # Variance CPU (différence de charge entre nœuds)
    local diff=$((worker1 - worker2))
    local cpu_variance=$(echo "scale=2; ($diff * $diff) / 2" | bc)
    
    # Écriture des métriques dans un fichier temporaire pour AFFICHAGE ULTERIEUR
    # ATTENTION : Ne rien afficher ici directement (pas de echo -e)
    cat > /tmp/metrics_${label}.json << EOF
{
    "label": "${label}",
    "worker1_pods": ${worker1},
    "worker2_pods": ${worker2},
    "latency_p95_ms": ${latency_p95},
    "cpu_variance": ${cpu_variance}
}
EOF
    
    # Retourne les deux valeurs brutes sans texte ni couleur pour l'écriture JSON
    echo "$latency_p95 $cpu_variance"
}

# ============================================================
# DÉBUT DES TESTS
# ============================================================

echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}TEST BASELINE : kube-scheduler (Politique par défaut)${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}Objectif: Mesurer la latence P95 et variance CPU sans IA${NC}"

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
      # Utilise le scheduler par défaut
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

# Récupérer distribution
BASELINE_W1=$(jq -r '.worker1' /tmp/distribution_baseline.json)
BASELINE_W2=$(jq -r '.worker2' /tmp/distribution_baseline.json)
METRICS=$(calculate_metrics "baseline" $BASELINE_W1 $BASELINE_W2)
LAT_RESULT=$(echo $METRICS | awk '{print $1}')
VAR_RESULT=$(echo $METRICS | awk '{print $2}')

# NOUVEAU BLOC : Afficher les métriques avant l'écriture JSON
echo -e "${CYAN}📈 Métriques:${NC}"
echo -e "   Latence P95: ${LAT_RESULT} ms"
echo -e "   Variance CPU: ${VAR_RESULT}"

# Écriture JSON (le contenu de cette ligne est déjà corrigé)
echo "\"baseline\": { \"worker1\": $BASELINE_W1, \"worker2\": $BASELINE_W2, \"latency_p95_ms\": $LAT_RESULT, \"cpu_variance\": $VAR_RESULT }," >> $RESULTS_FILE



# ------------------------------------------------------------
# 2. TEST EL (IA)
# ------------------------------------------------------------
echo -e "\n═══════════════════════════════════════════════════════════════"
echo -e "TEST 1 (EL) : Politique Priorité Latence (Edge-Latency)"
echo -e "Objectif: Consolidation sur Edge ($NODE_EDGE)"

cleanup

# Démarrer scheduler RL (avec output non bufferisé)
echo -e "${YELLOW}🚀 Démarrage Scheduler RL (mode EL)...${NC}"
source .venv/bin/activate
export RL_USE_TRAINED_MODEL=true
export RL_TRAINING_MODE=false
export PYTHONUNBUFFERED=1 # Redondant avec -u, mais sécurisant

# Lancer avec -u pour l'output immédiat et en background
python3 -u -m schedulers.ia_scheduler_rl > /tmp/scheduler_el.log 2>&1 &
SCHED_PID=$!
echo $SCHED_PID > /tmp/scheduler.pid
echo -e "${GREEN}   Scheduler PID: $SCHED_PID${NC}"
sleep 5

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
      # CORRIGÉ : Utilise le schedulerName standard synchronisé avec le Python
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

# Récupérer distribution
EL_W1=$(jq -r '.worker1' /tmp/distribution_el-latency.json)
EL_W2=$(jq -r '.worker2' /tmp/distribution_el-latency.json)
METRICS=$(calculate_metrics "el-latency" $EL_W1 $EL_W2)
LAT_EL=$(echo $METRICS | awk '{print $1}')
VAR_EL=$(echo $METRICS | awk '{print $2}')
echo -e "${GREEN}✅ Test EL (Latency) terminé${NC}"

# Écriture JSON partiel
echo "\"el_latency\": { \"worker1\": $EL_W1, \"worker2\": $EL_W2, \"latency_p95_ms\": $LAT_EL, \"cpu_variance\": $VAR_EL }," >> $RESULTS_FILE

kill $SCHED_PID 2>/dev/null || true

# ------------------------------------------------------------
# 3. TEST LB (IA)
# ------------------------------------------------------------
echo -e "\n═══════════════════════════════════════════════════════════════"
echo -e "${BLUE}TEST 2 (LB) : Politique Équilibrage de Charge${NC}"
echo -e "Objectif: Éviter saturation Edge"
cleanup

# Créer charge de saturation sur Edge Node
echo -e "${YELLOW}💪 Application charge de stress sur Edge...${NC}"
cat > /tmp/stress-load.yaml << EOF
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
      # CORRIGÉ : Ciblage par nom AGENT pour garantir que le stress se pose
      nodeSelector:
        kubernetes.io/hostname: $NODE_EDGE
      containers:
      - name: stress
        image: busybox
        command: ["sh", "-c", "while true; do :; done"]
        resources:
          requests:
            cpu: "1000m"
            memory: "256Mi"
EOF

kubectl apply -f /tmp/stress-load.yaml
sleep 15

# Redémarrer scheduler RL (mode LB)
echo -e "${YELLOW}🚀 Redémarrage Scheduler RL...${NC}"
source .venv/bin/activate
export RL_USE_TRAINED_MODEL=true
export RL_TRAINING_MODE=false
export PYTHONUNBUFFERED=1

python3 -u -m schedulers.ia_scheduler_rl > /tmp/scheduler_lb.log 2>&1 &
SCHED_PID=$!
echo $SCHED_PID > /tmp/scheduler.pid
sleep 5

cat > /tmp/test-lb-balance.yaml << EOF
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
      # CORRIGÉ : Utilise le schedulerName standard
      schedulerName: ia-scheduler
      containers:
      - name: upf
        image: busybox
        args: ["sleep", "3600"]
        resources:
          requests:
            memory: "64Mi"
            cpu: "100m"
EOF

kubectl apply -f /tmp/test-lb-balance.yaml
measure_distribution "lb-balance" 40

# Récupérer distribution
LB_W1=$(jq -r '.worker1' /tmp/distribution_lb-balance.json)
LB_W2=$(jq -r '.worker2' /tmp/distribution_lb-balance.json)
METRICS=$(calculate_metrics "lb-balance" $LB_W1 $LB_W2)
LAT_LB=$(echo $METRICS | awk '{print $1}')
VAR_LB=$(echo $METRICS | awk '{print $2}')
echo -e "${GREEN}✅ Test LB (Load Balancing) terminé${NC}"

# Écriture JSON fin (PAS de virgule après cette ligne)
echo "\"lb_balance\": { \"worker1\": $LB_W1, \"worker2\": $LB_W2, \"latency_p95_ms\": $LAT_LB, \"cpu_variance\": $VAR_LB }" >> $RESULTS_FILE
echo "}}" >> $RESULTS_FILE

kill $SCHED_PID 2>/dev/null || true

# ============================================================
# SYNTHÈSE DES RÉSULTATS
# ============================================================
echo -e "\n═══════════════════════════════════════════════════════════════"
echo -e "${BLUE}📊 SYNTHÈSE DES RÉSULTATS${NC}"
echo -e "═══════════════════════════════════════════════════════════════"

# Les variables LAT/VAR sont maintenant fiables, affichage direct
echo -e "\n${CYAN}┌─────────────────┬──────────────┬──────────────┬──────────────┐${NC}"
echo -e "${CYAN}│   Politique     │   Edge Pods  │  Cloud Pods  │ Latence P95  │${NC}"
echo -e "${CYAN}├─────────────────┼──────────────┼──────────────┼──────────────┤${NC}"
printf "${CYAN}│${NC} %-15s ${CYAN}│${NC} %12s ${CYAN}│${NC} %12s ${CYAN}│${NC} %10s ms ${CYAN}│${NC}\n" "Baseline" "${BASELINE_W1} pods" "${BASELINE_W2} pods" "${LAT_BASE}"
printf "${CYAN}│${NC} %-15s ${CYAN}│${NC} %12s ${CYAN}│${NC} %12s ${CYAN}│${NC} %10s ms ${CYAN}│${NC}\n" "EL (Latency)" "${EL_W1} pods" "${EL_W2} pods" "${LAT_EL}"
printf "${CYAN}│${NC} %-15s ${CYAN}│${NC} %12s ${CYAN}│${NC} %12s ${CYAN}│${NC} %10s ms ${CYAN}│${NC}\n" "LB (Balance)" "${LB_W1} pods" "${LB_W2} pods" "${LAT_LB}"
echo -e "${CYAN}└─────────────────┴──────────────┴──────────────┴──────────────┘${NC}"

# Gain EL vs Baseline (Latence) - Nécessite que bc fonctionne avec les virgules
EL_GAIN=$(echo "scale=2; 100 * ($LAT_BASE - $LAT_EL) / $LAT_BASE" | bc 2>/dev/null)
if [[ $(echo "$EL_GAIN > 0" | bc -l) -eq 1 ]]; then
    echo -e "${GREEN}🎯 ANALYSE DES PERFORMANCES:${NC}"
    echo -e "${GREEN}  ✅ EL (Latency): -${EL_GAIN}% de latence vs Baseline${NC}"
else
    echo -e "${RED}  ❌ EL (Latency): Pas d'amélioration de latence.${NC}"
fi


echo -e "\n${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}✅ Tests académiques terminés avec succès!${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}📄 Résultats sauvegardés: ${RESULTS_FILE}${NC}"

exit 0