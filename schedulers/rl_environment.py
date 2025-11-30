# schedulers/rl_environment.py
import numpy as np
from typing import Tuple, List
from kubernetes import client

class KubernetesSchedulingEnv:
    def __init__(self, v1_api: client.CoreV1Api):
        self.v1_api = v1_api
        self.state_size = 7
        
        # Un seul poids compte : La Latence
        self.LATENCY_WEIGHT = 200.0     

    def reset(self, pod_to_schedule: str) -> Tuple[np.ndarray, List[str]]:
        nodes = self.v1_api.list_node().items
        candidate_nodes = []
        for n in nodes:
            if "agent" in n.metadata.name:
                candidate_nodes.append(n)
        
        if not candidate_nodes: candidate_nodes = nodes
        candidate_nodes.sort(key=lambda x: x.metadata.name)
        node_names = [n.metadata.name for n in candidate_nodes]
        
        states = []
        for node_name in node_names:
            states.append(self._get_node_state(node_name))
            
        return np.array(states), node_names

    def _get_node_state(self, node_name: str) -> np.ndarray:
        # Identification simple : Agent-0 est rapide (1.0), les autres non (0.0)
        is_low_latency = 1.0 if "agent-0" in node_name else 0.0
        
        # On ignore le CPU (0.0 partout)
        return np.array([is_low_latency, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0])
    
    def calculate_reward(self, action_idx: int, states: np.ndarray, node_names: List[str]) -> float:
        node_state = states[action_idx]
        is_low_latency = (node_state[0] == 1.0)
        
        # Logique binaire pure
        if is_low_latency:
            return 100.0  # REWARD MAXIMALE (C'est le bon nœud)
        else:
            return 10.0   # REWARD FAIBLE (C'est le mauvais nœud)