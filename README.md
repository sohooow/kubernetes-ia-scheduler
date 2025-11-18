# kubernetes-ia-scheduler

**Scheduler Kubernetes personnalisé (IA)** qui sélectionne intelligemment les nœuds en fonction d'une heuristique pondérée combinant **latence** et **charge CPU**.

## 🎯 Fonctionnalités

- **Scoring intelligent** : algorithme pondéré `Score = W_L × (1/latence) + W_U × (1/(1+CPU))`
- **Poids configurables** : ajustez `W_L` (latence) et `W_U` (charge) selon vos besoins
- **Déploiement flexible** : fonctionne en local (Python) ou dans le cluster (conteneurisé)
- **Fallback robuste** : binding standard + patch fallback pour compatibilité
- **RBAC complet** : permissions Kubernetes configurées pour production

## 📁 Structure du projet

```
├── ia_scheduler.py          # Scheduler principal (watch + placement)
├── scoring_logic.py          # Logique de scoring avec poids W_L/W_U
├── Dockerfile                # Image Docker du scheduler
├── ia-scheduler-deploy.yaml  # Manifest K8s (RBAC + Deployment)
├── requirements.txt          # Dépendances Python
├── upf-pod-*.yaml           # Manifests de test
└── stress-base-load.yaml    # Charge de travail pour tests
```

## 🚀 Déploiement

### Option 1 : Déploiement dans Kubernetes (Recommandé)

#### Étape 1 : Créer/configurer le cluster

**Avec k3d (NexSlice) :**
```bash
# Créer un cluster k3d avec 3 nœuds
k3d cluster create nexslice-cluster
k3d node create nexslice-worker-1 --cluster nexslice-cluster --role agent
k3d node create nexslice-worker-2 --cluster nexslice-cluster --role agent

# Labelliser les nœuds pour simuler différentes latences
kubectl label node k3d-nexslice-worker-1-0 type=low-latency
kubectl label node k3d-nexslice-worker-2-0 type=standard
```

**Avec kind :**
```bash
# Créer un cluster kind multi-nœuds
kind create cluster --config kind-config.yaml

# Labelliser les nœuds
kubectl label node kind-worker type=low-latency
kubectl label node kind-worker2 type=standard
```

#### Étape 2 : Déployer le scheduler

```bash
# Déployer le scheduler avec RBAC
kubectl apply -f ia-scheduler-deploy.yaml

# Vérifier le déploiement
kubectl get pods -l app=custom-ia-scheduler
kubectl logs deployment/ia-scheduler-deployment
```

#### Étape 3 : Tester avec des pods

```bash
# Déployer des pods utilisant le scheduler IA
kubectl apply -f upf-pod-ia-L.yaml

# Observer la distribution
kubectl get pods -o wide

# Voir les décisions du scheduler
kubectl logs -f deployment/ia-scheduler-deployment
```

### Option 2 : Exécution locale (Développement)

```bash
# 1. Créer/activer un virtualenv
python -m venv .venv
source .venv/bin/activate

# 2. Installer les dépendances
pip install -r requirements.txt

# 3. Lancer le scheduler localement
python ia_scheduler.py
```

## 🔧 Configuration

### Ajuster les poids du scheduler

Éditez `scoring_logic.py` :

```python
# Scénario 1 : Privilégier la latence (fonctions 5G critiques)
W_L = 0.8  # Poids latence
W_U = 0.2  # Poids charge
CPU_THRESHOLD = 2.0  # Seuil CPU pour pénalité

# Scénario 2 : Privilégier l'équilibrage de charge
W_L = 0.2
W_U = 0.8
```

**Algorithme de scoring amélioré :**
```python
L_score = (50.0 / L_node) ** 2  # Formule quadratique pour amplifier les différences
U_score = 1.0/(1.0+U_cpu) if U_cpu < CPU_THRESHOLD else 0.1/(1.0+U_cpu)  # Pénalité pour surcharge
score = (W_L * L_score) + (W_U * U_score)
```

Puis reconstruisez l'image Docker :
```bash
docker build -t soohow/ia-scheduler:latest .
docker push soohow/ia-scheduler:latest
kubectl rollout restart deployment ia-scheduler-deployment
```

### Configurer Prometheus (optionnel)

Pour obtenir les métriques CPU réelles via Prometheus :

```bash
# Installer Prometheus dans le cluster
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/main/bundle.yaml

# Port-forward pour accès local (si scheduler tourne localement)
kubectl port-forward -n monitoring svc/prometheus 9090:9090
```

Si Prometheus n'est pas disponible, le scheduler utilise automatiquement un fallback basé sur la somme des `requests` CPU des pods.

## 📊 Résultats de tests

### Test avec W_L=0.8 (priorité latence) - Algorithme amélioré

**Distribution observée sur cluster NexSlice (3 nœuds, 5 replicas) :**

| Nœud | Type | Latence simulée | Pods déployés | Score moyen |
|------|------|----------------|---------------|-------------|
| **k3d-nexslice-worker-1-0** | low-latency | 10ms | **5 pods** ✅ | **~20.14** |
| k3d-nexslice-worker-2-0 | standard | 50ms | 0 pods | ~0.97 |
| k3d-nexslice-cluster-server-0 | control-plane | 50ms | 0 pods | ~0.94 |

**Résultat :** Avec la formule quadratique `(50.0/latency)²`, le scheduler respecte parfaitement la pondération W_L=0.8 en créant un **écart de score de ~20x** entre les nœuds low-latency et standard. Tous les 5 pods sont placés sur le nœud à faible latence comme attendu.

**Latence P95 estimée :** **10ms** (100% des pods sur nœud low-latency)

## 🐳 Image Docker

Image publique disponible sur Docker Hub :
```bash
docker pull soohow/ia-scheduler:latest
```

## 📝 Notes importantes

- **schedulerName** : Les pods doivent spécifier `schedulerName: custom-ia-scheduler` pour être traités par ce scheduler
- **Coexistence** : Peut tourner en parallèle du scheduler par défaut de Kubernetes
- **Permissions RBAC** : Le manifest `ia-scheduler-deploy.yaml` configure automatiquement les permissions nécessaires
- **Metrics API** : Si `kubectl top` renvoie une erreur, installez `metrics-server` dans votre cluster

## 🔗 Liens

- **GitHub** : https://github.com/sohooow/kubernetes-ia-scheduler
- **Docker Hub** : https://hub.docker.com/r/soohow/ia-scheduler

## 📄 Licence

MIT (à ajouter si besoin)
