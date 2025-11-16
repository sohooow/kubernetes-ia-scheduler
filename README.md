# kubernetes-ia-scheduler

Petit projet de démonstration d'un scheduler Kubernetes personnalisé (IA) qui sélectionne un nœud
en fonction d'une heuristique pondérée sur la latence et la charge CPU.

Contenu principal:
- `ia_scheduler.py` : watcher + scheduler principal qui bind/patch des pods.
- `scoring_logic.py` : logique de scoring (poids W_L / W_U configurables).
- `*.yaml` : manifests pour déployer des pods/charges de test.

Quick start (local, avec kind):

1. Créer/activer un virtualenv Python et installer dépendances:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. S'assurer d'un cluster (kind/minikube) et déployer les manifests de test.

3. Lancer le scheduler:

```bash
source .venv/bin/activate
python ia_scheduler.py
```

Notes:
- `scoring_logic.py` contient les poids `W_L` (latence) et `W_U` (charge). Changez-les pour vos scénarios.
- Si `kubectl top` renvoie `Metrics API not available`, installez `metrics-server` dans votre cluster.
