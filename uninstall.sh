#!/bin/bash
# Script de nettoyage radical de l'environnement K3D et Docker

echo "================================================="
echo "🧹 DÉMARRAGE DU NETTOYAGE RADICAL DU SYSTÈME"
echo "================================================="

# 1. SUPPRESSION DES CLUSTERS K3D
echo -e "\n--- Suppression de tous les clusters K3d..."
k3d cluster delete --all || true

# 2. ARRÊT ET SUPPRESSION DES CONTENEURS DOCKER
echo -e "\n--- Arrêt et suppression de TOUS les conteneurs..."
# 'docker ps -aq' liste tous les conteneurs (actifs et stoppés)
docker rm -f $(docker ps -aq) 2>/dev/null || true

# 3. PURGE DU SYSTÈME DOCKER (IMAGES ET VOLUMES)
echo -e "\n--- Suppression des images, volumes et caches non utilisés..."
# -a: supprime toutes les images non utilisées (pas seulement les dangling)
# --volumes: supprime les volumes non utilisés
# -f: force sans confirmation
docker system prune -a --volumes -f

# 4. NETTOYAGE LOCAL DU PROJET
echo -e "\n--- Nettoyage des environnements Python (.venv) et caches..."
rm -rf .venv
rm -rf __pycache__
rm -rf schedulers/__pycache__

echo -e "\n✅ Nettoyage terminé. Le système est prêt à être recréé."