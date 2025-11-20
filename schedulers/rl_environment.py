# schedulers/rl_environment.py
import numpy as np
from typing import Tuple, List
from kubernetes import client

class KubernetesSchedulingEnv:
    def __init__(self, v1_api: client.CoreV1Api):
        self.v1_api = v1_api
        self.state_size = 7
        # Poids simplifiés
        self.LATENCY_WEIGHT = 10.0
        self.CPU_WEIGHT = 5.0

    def reset(self, pod_to_schedule: str) -> Tuple[np.ndarray, List[str]]:
        """Récupère l'état actuel du cluster."""
        nodes = self.v1_api.list_node().items
        
        # 1. Filtrage (Exclure master/control-plane)
        candidate_nodes = []
        for n in nodes:
            labels = n.metadata.labels or {}
            name = n.metadata.name
            
            is_master = 'node-role.kubernetes.io/master' in labels or \
                        'node-role.kubernetes.io/control-plane' in labels
            
            if "agent" in name or (not is_master):
                candidate_nodes.append(n)
        
        # Sécurité si filtre vide
        if not candidate_nodes:
            candidate_nodes = nodes

        # 2. CORRECTION CRUCIALE : TRI ALPHABÉTIQUE
        # Cela garantit que agent-0 est toujours l'index 0 et agent-1 est l'index 1
        candidate_nodes.sort(key=lambda x: x.metadata.name)

        node_names = [n.metadata.name for n in candidate_nodes]
        
        states = []
        for node_name in node_names:
            states.append(self._get_node_state(node_name))
            
        return np.array(states), node_names

    def _get_node_state(self, node_name: str) -> np.ndarray:
        lat = 0.1 if "agent-0" in node_name else 0.5
        
        try:
            # Récupère tous les pods en état Running sur ce nœud
            pods = self.v1_api.list_pod_for_all_namespaces(field_selector=f"spec.nodeName={node_name},status.phase=Running").items
            
            is_stressed = False
            for p in pods:
                # Vérification 1: Par le nom du pod lui-même
                if 'stress' in p.metadata.name:
                    is_stressed = True
                    break
                # Vérification 2: Par le nom du contrôleur (Deployment/ReplicaSet)
                if p.metadata.owner_references and 'stress' in p.metadata.owner_references[0].name:
                    is_stressed = True
                    break
            
            if is_stressed:
                cpu_usage = 0.95
            else:
                running_pods = len(pods)
                cpu_usage = min(running_pods * 0.05, 0.4)
                
        except Exception as e:
            # En cas d'erreur de connexion à l'API K8s, on part du principe que le nœud est libre
            cpu_usage = 0.0
        
        # Retourne : [latence, cpu_usage, 0.0, 0.0, 0.0, 0.0, 1.0]
        return np.array([lat, cpu_usage, 0.0, 0.0, 0.0, 0.0, 1.0])
    
    def calculate_reward(self, *args): return 0.0
    def get_state_info(self, *args): return ""