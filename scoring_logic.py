# scoring_logic.py

import requests
import json
from kubernetes import client
from typing import Dict, Optional

# IMPORTANT : L'URL de votre Prometheus après avoir fait un 'kubectl port-forward'
# Si vous avez exposé Prometheus localement, c'est généralement cette adresse.
PROMETHEUS_URL = "http://127.0.0.1:9090"

def get_real_cpu_usage(node_name: str) -> float:
    """
    Récupère l'utilisation CPU en % (0.0 à 1.0) via l'API Prometheus.
    Utilise PromQL pour obtenir l'utilisation moyenne sur les 5 dernières minutes.
    """
    # Note: Assurez-vous que node_exporter est bien installé sur vos nœuds Kind
    # pour que la métrique 'node_cpu_seconds_total' soit disponible.
    query = f'1 - avg(rate(node_cpu_seconds_total{{mode="idle", instance=~"{node_name}.*"}}[5m]))'
    
    try:
        response = requests.get(f'{PROMETHEUS_URL}/api/v1/query', params={'query': query}, timeout=5)
        response.raise_for_status() # Lève une exception pour les codes d'erreur HTTP (4xx ou 5xx)
        
        results = response.json().get('data', {}).get('result', [])
        
        if results:
            # La valeur est un tableau [timestamp, 'valeur'], on prend la valeur
            return float(results[0]['value'][1])
    
    except requests.exceptions.ConnectionError:
        print(f"Erreur: Impossible de se connecter à Prometheus à {PROMETHEUS_URL}")
    except Exception as e:
        print(f"Erreur lors de la requête Prometheus: {e}")
        
    return 0.0 # Retourne 0.0 si la métrique n'est pas trouvée ou en cas d'erreur


def get_node_metrics(v1_api: client.CoreV1Api, node_name: str) -> Dict[str, float]:
    """
    Collecte toutes les métriques nécessaires pour un nœud donné.
    """
    
    # 1. Métrique réelle : Utilisation CPU via Prometheus
    cpu_usage = get_real_cpu_usage(node_name)

    # Si Prometheus n'est pas disponible (cpu_usage == 0.0),
    # fallback sur la somme des CPU demandés par les pods qui résident
    # déjà sur le nœud (approximation de la charge par requests).
    if cpu_usage == 0.0:
        try:
            pods_on_node = v1_api.list_pod_for_all_namespaces(field_selector=f"spec.nodeName={node_name}").items
            requested_cpu_sum = 0.0
            for p in pods_on_node:
                for c in p.spec.containers:
                    reqs = getattr(c.resources, 'requests', None) or {}
                    cpu_req = reqs.get('cpu')
                    if cpu_req:
                        # cpu_req peut être '100m' ou '1'
                        if str(cpu_req).endswith('m'):
                            requested_cpu_sum += float(str(cpu_req)[:-1]) / 1000.0
                        else:
                            try:
                                requested_cpu_sum += float(cpu_req)
                            except Exception:
                                pass
            # Utiliser la somme des requests comme approximation (en cœurs)
            cpu_usage = requested_cpu_sum
        except Exception:
            # Si erreur, rester sur 0.0
            cpu_usage = 0.0
    
    # 2. Métrique simulée : Latence (basée sur l'étiquette K8s)
    try:
        node_obj = v1_api.read_node(name=node_name)
        latency_type = node_obj.metadata.labels.get('type', 'default')
        
        # Latence de base simulée (ms). Les nœuds 'low-latency' sont privilégiés.
        base_latency = 10.0 if latency_type == 'low-latency' else 50.0 
    except Exception:
        base_latency = 50.0

    return {'latency': base_latency, 'cpu_usage': cpu_usage}


def calculate_score_and_select_node(v1_api: client.CoreV1Api, pod_name: str) -> Optional[str]:
    """
    Applique l'heuristique pondérée pour sélectionner le meilleur nœud.
    """
    
    nodes = v1_api.list_node().items
    
    # Filtre de base : Ignorer le control-plane pour le placement des pods de travail
    candidate_nodes = [n for n in nodes if n.metadata.labels.get('kubernetes.io/role') != 'control-plane']
    
    best_score = -float('inf')
    best_node_name = None
    
    # --- DÉFINITION DES POIDS DE L'IA ---
    # Privilégier fortement la latence (pour fonctions 5G critiques)
    W_L = 0.8
    # W_U (Charge) pour l'équilibrage général
    W_U = 0.2
    
    # Seuil de charge CPU au-delà duquel on pénalise fortement un nœud
    CPU_THRESHOLD = 2.0  # 2 cœurs de charge totale
    
    print("\n--- Démarrage de l'heuristique de scoring ---")
    
    for node in candidate_nodes:
        node_name = node.metadata.name
        metrics = get_node_metrics(v1_api, node_name)
        
        L_node = metrics['latency']
        U_cpu = metrics['cpu_usage']
        
        # Composante Latence (L_score) : Utiliser un exposant pour amplifier les différences
        # Score latence normalisé : (Latence_max / Latence_noeud)^2
        # Plus L_node est petit, plus L_score est grand (effet quadratique)
        L_score = (50.0 / L_node) ** 2  # 50ms = latence max de référence
        
        # Composante Charge (U_score) : Pénaliser fortement les nœuds surchargés
        # Tant que CPU < seuil, score élevé. Au-delà, pénalité exponentielle
        if U_cpu < CPU_THRESHOLD:
            U_score = 1.0 / (1.0 + U_cpu)
        else:
            # Pénalité forte pour nœuds surchargés
            U_score = 0.1 / (1.0 + U_cpu)
        
        # Score final pondéré
        score = (W_L * L_score) + (W_U * U_score)
        
        print(f"Nœud: {node_name} | Latence: {L_node}ms | Usage CPU: {U_cpu:.2f} | Score: {score:.4f}")
        
        if score > best_score:
            best_score = score
            best_node_name = node_name
            
    print(f"--- Fin du scoring. Meilleur nœud sélectionné: {best_node_name} (Score: {best_score:.4f}) ---")
    return best_node_name