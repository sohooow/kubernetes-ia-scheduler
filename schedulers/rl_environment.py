# rl_environment.py
"""
Environnement de Reinforcement Learning pour le scheduler Kubernetes.

Amélioré avec les contributions de:
- Wang et al. (2023) - Deep RL for Edge Kubernetes Task Scheduling
- Jian et al. (2024) - DRS: Deep RL Enhanced Kubernetes Scheduler
- Thèse: Optimisation multi-objectifs avec affinity et fragmentation

État enrichi: [latence, cpu, mem, nb_pods, fragmentation, affinity_score, network_bandwidth]
Action: sélectionner un nœud parmi les candidats
Récompense multi-objectifs: -latence - surcharge + équilibrage + affinity - fragmentation
"""

import numpy as np
from typing import Dict, List, Tuple, Optional
from kubernetes import client


class KubernetesSchedulingEnv:
    """
    Environnement RL avancé pour le placement de pods dans Kubernetes.
    Intègre métriques de fragmentation et contraintes d'affinity.
    """
    
    def __init__(self, v1_api: client.CoreV1Api):
        self.v1_api = v1_api
        self.current_pod = None
        self.state_size = 7  # [latence, cpu, mem, nb_pods, fragmentation, affinity, bandwidth]
        self.action_space = []  # Liste des nœuds candidats
        
        # Hyperparamètres de récompense (inspirés de l'article)
        self.LATENCY_WEIGHT = 10.0          # Poids latence (critique 5G)
        self.CPU_WEIGHT = 8.0               # Poids CPU (augmenté pour LB)
        self.MEMORY_WEIGHT = 5.0            # Poids mémoire
        self.BALANCE_BONUS = 3.0            # Bonus équilibrage
        self.OVERLOAD_PENALTY = 50.0        # Pénalité surcharge (augmentée)
        self.FRAGMENTATION_PENALTY = 8.0    # Nouvelle: pénalité fragmentation
        self.AFFINITY_BONUS = 5.0           # Nouveau: bonus affinity
        self.NETWORK_WEIGHT = 4.0           # Nouveau: poids bande passante
        
        # Seuils de surcharge (abaissés pour détecter saturation plus tôt)
        self.CPU_THRESHOLD = 0.60           # 60% CPU = début surcharge
        self.MEMORY_THRESHOLD = 0.70        # 70% mémoire = début surcharge
        
    def reset(self, pod_to_schedule: str) -> Tuple[np.ndarray, List[str]]:
        """
        Initialise l'environnement pour un nouveau pod à placer.
        
        Returns:
            - states: array de shape (n_nodes, state_size) - état enrichi de chaque nœud
            - node_names: liste des noms de nœuds candidats
        """
        self.current_pod = pod_to_schedule
        
        # Récupérer les nœuds candidats (exclure control-plane)
        nodes = self.v1_api.list_node().items
        candidate_nodes = [
            n for n in nodes 
            if 'node-role.kubernetes.io/control-plane' not in n.metadata.labels
            and 'node-role.kubernetes.io/master' not in n.metadata.labels
        ]
        
        self.action_space = [node.metadata.name for node in candidate_nodes]
        
        # Collecter l'état enrichi de chaque nœud
        states = []
        for node in candidate_nodes:
            state = self._get_node_state(node.metadata.name)
            states.append(state)
        
        return np.array(states), self.action_space
    
    def _get_node_state(self, node_name: str) -> np.ndarray:
        """
        Récupère l'état enrichi d'un nœud: 
        [latence, cpu_usage, mem_usage, nb_pods, fragmentation, affinity, bandwidth]
        """
        # 1. Latence simulée via label
        try:
            node_obj = self.v1_api.read_node(name=node_name)
            latency_type = node_obj.metadata.labels.get('type', 'standard')
            latency = 10.0 if latency_type == 'low-latency' else 50.0
        except Exception:
            latency = 50.0
        
        # 2. Usage CPU (normalisé 0-1)
        # Pour l'instant, approximation via somme des requests (à améliorer avec Prometheus)
        cpu_usage = self._get_cpu_usage_normalized(node_name)
        
        # 3. Usage Mémoire (normalisé 0-1)
        mem_usage = self._get_memory_usage_normalized(node_name)
        
        # 4. Nombre de pods sur le nœud
        try:
            pods_on_node = self.v1_api.list_pod_for_all_namespaces(
                field_selector=f"spec.nodeName={node_name}"
            ).items
            nb_pods = len([p for p in pods_on_node if p.status.phase == 'Running'])
        except Exception:
            nb_pods = 0
        
        # 5. Fragmentation des ressources (inspiré de l'article)
        # Mesure de la "fragmentation" = variance entre CPU et Mémoire disponible
        fragmentation = self._calculate_fragmentation(node_name, cpu_usage, mem_usage)
        
        # 6. Score d'affinity (basé sur les labels du pod et du nœud)
        affinity_score = self._calculate_affinity_score(node_name)
        
        # 7. Bande passante réseau disponible (simulée via label zone)
        bandwidth = self._get_network_bandwidth(node_name)
        
        # Normalisation: latence en [0,1], nb_pods en [0,1] (max 50 pods par nœud)
        normalized_latency = latency / 100.0  # 0ms -> 0.0, 100ms -> 1.0
        normalized_nb_pods = min(nb_pods / 50.0, 1.0)
        
        return np.array([
            normalized_latency, 
            cpu_usage, 
            mem_usage, 
            normalized_nb_pods,
            fragmentation,
            affinity_score,
            bandwidth
        ])
    
    def _get_cpu_usage_normalized(self, node_name: str) -> float:
        """
        Retourne l'usage CPU normalisé [0,1].
        Fallback: somme des requests des pods / capacité totale du nœud.
        """
        try:
            # Capacité totale du nœud
            node_obj = self.v1_api.read_node(name=node_name)
            total_cpu_str = node_obj.status.allocatable.get('cpu', '0')
            total_cpu = self._parse_cpu(total_cpu_str)
            
            if total_cpu == 0:
                return 0.0
            
            # Somme des CPU requests des pods
            pods_on_node = self.v1_api.list_pod_for_all_namespaces(
                field_selector=f"spec.nodeName={node_name}"
            ).items
            
            requested_cpu_sum = 0.0
            for p in pods_on_node:
                if p.status.phase == 'Running':
                    for c in p.spec.containers:
                        reqs = getattr(c.resources, 'requests', None) or {}
                        cpu_req = reqs.get('cpu')
                        if cpu_req:
                            requested_cpu_sum += self._parse_cpu(str(cpu_req))
            
            # Normaliser par la capacité totale
            usage_ratio = requested_cpu_sum / total_cpu
            return min(usage_ratio, 1.0)
        
        except Exception as e:
            print(f"Erreur CPU pour {node_name}: {e}")
            return 0.0
    
    def _get_memory_usage_normalized(self, node_name: str) -> float:
        """
        Retourne l'usage mémoire normalisé [0,1].
        """
        try:
            # Capacité mémoire totale
            node_obj = self.v1_api.read_node(name=node_name)
            total_mem_str = node_obj.status.allocatable.get('memory', '0')
            total_mem = self._parse_memory(total_mem_str)
            
            if total_mem == 0:
                return 0.0
            
            # Somme des memory requests des pods
            pods_on_node = self.v1_api.list_pod_for_all_namespaces(
                field_selector=f"spec.nodeName={node_name}"
            ).items
            
            requested_mem_sum = 0.0
            for p in pods_on_node:
                if p.status.phase == 'Running':
                    for c in p.spec.containers:
                        reqs = getattr(c.resources, 'requests', None) or {}
                        mem_req = reqs.get('memory')
                        if mem_req:
                            requested_mem_sum += self._parse_memory(str(mem_req))
            
            # Normaliser
            usage_ratio = requested_mem_sum / total_mem
            return min(usage_ratio, 1.0)
        
        except Exception as e:
            print(f"Erreur mémoire pour {node_name}: {e}")
            return 0.0
    
    def _parse_cpu(self, cpu_str: str) -> float:
        """Parse CPU string (e.g., '100m', '2') vers float en cœurs."""
        if str(cpu_str).endswith('m'):
            return float(str(cpu_str)[:-1]) / 1000.0
        try:
            return float(cpu_str)
        except:
            return 0.0
    
    def _parse_memory(self, mem_str: str) -> float:
        """Parse memory string (e.g., '1Gi', '512Mi') vers float en bytes."""
        mem_str = str(mem_str)
        
        if mem_str.endswith('Ki'):
            return float(mem_str[:-2]) * 1024
        elif mem_str.endswith('Mi'):
            return float(mem_str[:-2]) * 1024 * 1024
        elif mem_str.endswith('Gi'):
            return float(mem_str[:-2]) * 1024 * 1024 * 1024
        elif mem_str.endswith('Ti'):
            return float(mem_str[:-2]) * 1024 * 1024 * 1024 * 1024
        
        try:
            return float(mem_str)
        except:
            return 0.0
    
    def calculate_reward(
        self, 
        selected_node_idx: int, 
        states: np.ndarray, 
        node_names: List[str]
    ) -> float:
        """
        Calcule la récompense multi-objectifs après avoir placé un pod sur un nœud.
        
        Récompense enrichie (inspirée de l'article) :
        = -LATENCY_WEIGHT × latence 
          -CPU_WEIGHT × cpu_usage 
          -MEMORY_WEIGHT × mem_usage 
          +BALANCE_BONUS (si charge équilibrée)
          -OVERLOAD_PENALTY (si surcharge)
          -FRAGMENTATION_PENALTY × fragmentation
          +AFFINITY_BONUS × affinity_score
          -NETWORK_WEIGHT × (1 - bandwidth)
        """
        # État du nœud sélectionné (7 dimensions maintenant)
        selected_state = states[selected_node_idx]
        latency, cpu, mem, nb_pods, fragmentation, affinity, bandwidth = selected_state
        
        # Pénalité latence (critique pour 5G UPF)
        latency_penalty = self.LATENCY_WEIGHT * latency
        
        # Pénalité charge CPU (progressive avec saturation)
        # Si CPU > 60%, pénalité augmente exponentiellement
        cpu_penalty = self.CPU_WEIGHT * cpu
        if cpu > self.CPU_THRESHOLD:
            # Pénalité exponentielle pour saturation
            saturation_factor = ((cpu - self.CPU_THRESHOLD) / (1.0 - self.CPU_THRESHOLD)) ** 2
            cpu_penalty += self.OVERLOAD_PENALTY * saturation_factor
        
        # Pénalité charge mémoire
        mem_penalty = self.MEMORY_WEIGHT * mem
        
        # Pénalité forte si surcharge
        overload_penalty = 0.0
        if cpu > self.CPU_THRESHOLD or mem > self.MEMORY_THRESHOLD:
            overload_penalty = self.OVERLOAD_PENALTY
        
        # Bonus si la charge est équilibrée entre les nœuds
        mean_cpu = np.mean(states[:, 1])  # Moyenne CPU de tous les nœuds
        balance_bonus = 0.0
        if abs(cpu - mean_cpu) < 0.1:  # Proche de la moyenne
            balance_bonus = self.BALANCE_BONUS
        
        # Nouvelles composantes (inspirées de l'article)
        
        # Pénalité fragmentation (variance des ressources)
        fragmentation_penalty = self.FRAGMENTATION_PENALTY * fragmentation
        
        # Bonus affinity (si pod compatible avec nœud)
        affinity_bonus = self.AFFINITY_BONUS * affinity
        
        # Pénalité bande passante (favoriser nœuds avec + de bandwidth)
        network_penalty = self.NETWORK_WEIGHT * (1.0 - bandwidth)
        
        # Récompense totale multi-objectifs
        reward = (
            -latency_penalty 
            - cpu_penalty 
            - mem_penalty 
            + balance_bonus 
            - overload_penalty
            - fragmentation_penalty
            + affinity_bonus
            - network_penalty
        )
        
        return reward
    
    def _calculate_fragmentation(self, node_name: str, cpu_usage: float, mem_usage: float) -> float:
        """
        Calcule le score de fragmentation des ressources (inspiré de l'article).
        
        Fragmentation = variance entre CPU et mémoire disponibles.
        Score élevé = ressources déséquilibrées (ex: 90% CPU, 10% mem).
        """
        # Ressources disponibles
        cpu_available = 1.0 - cpu_usage
        mem_available = 1.0 - mem_usage
        
        # Calcul de la variance (fragmentation)
        mean_available = (cpu_available + mem_available) / 2.0
        variance = ((cpu_available - mean_available)**2 + (mem_available - mean_available)**2) / 2.0
        
        # Normaliser en [0, 1]
        fragmentation_score = min(variance * 2.0, 1.0)  # * 2 pour amplifier
        
        return fragmentation_score
    
    def _calculate_affinity_score(self, node_name: str) -> float:
        """
        Calcule le score d'affinity/anti-affinity (inspiré de l'article).
        
        Basé sur:
        - Labels du nœud (zone, type)
        - Pods déjà présents sur le nœud
        - Règles d'affinity du pod actuel (si définies)
        """
        try:
            node_obj = self.v1_api.read_node(name=node_name)
            node_labels = node_obj.metadata.labels or {}
            
            # Score basé sur les labels stratégiques
            score = 0.0
            
            # Bonus si nœud dans zone edge (pour UPF 5G)
            if node_labels.get('zone') == 'edge':
                score += 0.5
            
            # Bonus si type low-latency
            if node_labels.get('type') == 'low-latency':
                score += 0.3
            
            # Vérifier la diversité des pods (anti-affinity implicite)
            pods_on_node = self.v1_api.list_pod_for_all_namespaces(
                field_selector=f"spec.nodeName={node_name}"
            ).items
            
            # Bonus si peu de pods similaires (diversité)
            pod_apps = [p.metadata.labels.get('app', '') for p in pods_on_node if p.metadata.labels]
            unique_apps = len(set(pod_apps))
            total_pods = len(pod_apps) or 1
            diversity_ratio = unique_apps / total_pods
            score += diversity_ratio * 0.2
            
            return min(score, 1.0)
        
        except Exception:
            return 0.0
    
    def _get_network_bandwidth(self, node_name: str) -> float:
        """
        Estime la bande passante réseau disponible (simulée via labels).
        
        En production, utiliser métriques réseau réelles (Prometheus).
        """
        try:
            node_obj = self.v1_api.read_node(name=node_name)
            node_labels = node_obj.metadata.labels or {}
            
            # Simulation basée sur zone
            zone = node_labels.get('zone', 'core')
            
            if zone == 'edge':
                return 0.9  # Edge a plus de bande passante vers UE
            elif zone == 'core':
                return 0.6  # Core a bande passante modérée
            else:
                return 0.5  # Standard
        
        except Exception:
            return 0.5  # Valeur par défaut
    
    def get_state_info(self, states: np.ndarray, node_names: List[str]) -> str:
        """Retourne une description lisible de l'état enrichi pour le logging."""
        info = "\n--- État enrichi des nœuds ---\n"
        for i, node_name in enumerate(node_names):
            latency, cpu, mem, nb_pods, frag, affinity, bw = states[i]
            info += f"{node_name}:\n"
            info += f"  Latence: {latency*100:.1f}ms | CPU: {cpu*100:.0f}% | "
            info += f"Mem: {mem*100:.0f}% | Pods: {int(nb_pods*50)}\n"
            info += f"  Fragmentation: {frag:.2f} | Affinity: {affinity:.2f} | Bandwidth: {bw:.2f}\n"
        return info
