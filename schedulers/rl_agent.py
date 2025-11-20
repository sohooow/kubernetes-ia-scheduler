# rl_agent.py
"""
Agent de Deep Reinforcement Learning (DQN) pour le scheduler Kubernetes.

Implémente:
- Deep Q-Network (DQN) avec replay buffer
- Epsilon-greedy exploration
- Target network pour stabilité
- Sauvegarde/chargement du modèle entraîné

Inspiré de:
- Wang et al. (2023) - DRL for Edge Kubernetes
- Jian et al. (2024) - DRS Scheduler
"""

import numpy as np
import pickle
import os
from typing import List, Tuple, Optional
from collections import deque
import random

# Import optionnel de PyTorch (si disponible)
try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    print("PyTorch non disponible. Utilisation de Q-Learning tabulaire.")


class DQNetwork(nn.Module):
    """
    Réseau de neurones pour Deep Q-Learning.
    Architecture: state_size -> 64 -> 32 -> 1 (Q-value)
    """
    def __init__(self, state_size: int):
        super(DQNetwork, self).__init__()
        self.fc1 = nn.Linear(state_size, 64)
        self.fc2 = nn.Linear(64, 32)
        self.fc3 = nn.Linear(32, 1)  # Output: Q-value pour ce nœud
        
    def forward(self, x):
        x = torch.relu(self.fc1(x))
        x = torch.relu(self.fc2(x))
        return self.fc3(x)


class ReplayBuffer:
    """
    Buffer pour stocker les transitions (s, a, r, s') et faire du batch learning.
    """
    def __init__(self, capacity: int = 10000):
        self.buffer = deque(maxlen=capacity)
    
    def push(self, state, action_idx, reward, next_state, done):
        """Ajoute une transition au buffer."""
        self.buffer.append((state, action_idx, reward, next_state, done))
    
    def sample(self, batch_size: int):
        """Échantillonne un batch aléatoire."""
        return random.sample(self.buffer, min(batch_size, len(self.buffer)))
    
    def __len__(self):
        return len(self.buffer)


class RLSchedulerAgent:
    """
    Agent RL pour le placement de pods Kubernetes.
    Supporte DQN (si PyTorch disponible) ou Q-Learning tabulaire (fallback).
    """
    
    def __init__(
        self, 
        state_size: int = 7,  # Augmenté de 4 à 7 (avec fragmentation, affinity, bandwidth)
        use_dqn: bool = True,
        learning_rate: float = 0.001,
        gamma: float = 0.95,
        epsilon: float = 1.0,
        epsilon_min: float = 0.01,
        epsilon_decay: float = 0.995,
        model_path: str = "rl_scheduler_model.pth"
    ):
        self.state_size = state_size
        self.gamma = gamma  # Discount factor
        self.epsilon = epsilon  # Exploration rate
        self.epsilon_min = epsilon_min
        self.epsilon_decay = epsilon_decay
        self.model_path = model_path
        
        # Mode DQN ou Q-Learning tabulaire
        self.use_dqn = use_dqn and TORCH_AVAILABLE
        
        if self.use_dqn:
            # Deep Q-Network
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            self.policy_net = DQNetwork(state_size).to(self.device)
            self.target_net = DQNetwork(state_size).to(self.device)
            self.target_net.load_state_dict(self.policy_net.state_dict())
            self.target_net.eval()
            
            self.optimizer = optim.Adam(self.policy_net.parameters(), lr=learning_rate)
            self.criterion = nn.MSELoss()
            
            self.replay_buffer = ReplayBuffer(capacity=10000)
            self.batch_size = 32
            self.target_update_freq = 100
            self.train_step_counter = 0
            
            print(f"🧠 Agent DQN initialisé (device: {self.device})")
        else:
            # Q-Learning tabulaire (fallback simple)
            self.q_table = {}  # Dict: {state_hash: [q_values pour chaque nœud]}
            self.learning_rate = learning_rate
            print("📊 Agent Q-Learning tabulaire initialisé")
    
    def select_action(
        self, 
        states: np.ndarray, 
        node_names: List[str], 
        training: bool = True
    ) -> Tuple[int, str]:
        """
        Sélectionne un nœud en utilisant epsilon-greedy.
        
        Args:
            states: array (n_nodes, state_size)
            node_names: liste des noms de nœuds
            training: si True, utilise epsilon-greedy, sinon greedy pur
        
        Returns:
            (node_index, node_name)
        """
        # Exploration: action aléatoire
        if training and random.random() < self.epsilon:
            node_idx = random.randint(0, len(node_names) - 1)
            return node_idx, node_names[node_idx]
        
        # Exploitation: meilleur Q-value
        if self.use_dqn:
            q_values = self._get_q_values_dqn(states)
        else:
            q_values = self._get_q_values_tabular(states)
        
        # Sélectionner le nœud avec le meilleur Q-value
        best_node_idx = int(np.argmax(q_values))
        return best_node_idx, node_names[best_node_idx]
    
    def _get_q_values_dqn(self, states: np.ndarray) -> np.ndarray:
        """Calcule les Q-values avec le réseau de neurones."""
        self.policy_net.eval()
        with torch.no_grad():
            states_tensor = torch.FloatTensor(states).to(self.device)
            q_values = self.policy_net(states_tensor).cpu().numpy().flatten()
        return q_values
    
    def _get_q_values_tabular(self, states: np.ndarray) -> np.ndarray:
        """Calcule les Q-values avec la table Q."""
        q_values = []
        for state in states:
            state_hash = self._hash_state(state)
            if state_hash not in self.q_table:
                # Initialiser avec des valeurs neutres
                self.q_table[state_hash] = 0.0
            q_values.append(self.q_table[state_hash])
        return np.array(q_values)
    
    def _hash_state(self, state: np.ndarray) -> str:
        """Hash un état pour la Q-table (arrondi pour réduire dimensionnalité)."""
        rounded = np.round(state, decimals=2)
        return str(rounded.tolist())
    
    def update(
        self, 
        states: np.ndarray, 
        action_idx: int, 
        reward: float, 
        next_states: Optional[np.ndarray] = None,
        done: bool = True
    ):
        """
        Met à jour l'agent après une action (apprentissage).
        
        Args:
            states: états des nœuds avant l'action
            action_idx: index du nœud sélectionné
            reward: récompense obtenue
            next_states: états après l'action (pour Q-learning multi-step)
            done: True si l'épisode est terminé
        """
        if self.use_dqn:
            self._update_dqn(states, action_idx, reward, next_states, done)
        else:
            self._update_tabular(states, action_idx, reward, next_states, done)
        
        # Decay epsilon
        if self.epsilon > self.epsilon_min:
            self.epsilon *= self.epsilon_decay
    
    def _update_dqn(self, states, action_idx, reward, next_states, done):
        """Mise à jour DQN avec experience replay."""
        # Stocker la transition
        state = states[action_idx]  # État du nœud choisi
        next_state = next_states[action_idx] if next_states is not None else state
        
        self.replay_buffer.push(state, action_idx, reward, next_state, done)
        
        # Apprendre si assez d'expériences
        if len(self.replay_buffer) < self.batch_size:
            return
        
        # Échantillonner un batch
        batch = self.replay_buffer.sample(self.batch_size)
        
        states_batch = torch.FloatTensor([t[0] for t in batch]).to(self.device)
        rewards_batch = torch.FloatTensor([t[2] for t in batch]).to(self.device)
        next_states_batch = torch.FloatTensor([t[3] for t in batch]).to(self.device)
        dones_batch = torch.FloatTensor([t[4] for t in batch]).to(self.device)
        
        # Q-values actuelles
        self.policy_net.train()
        current_q = self.policy_net(states_batch).squeeze()
        
        # Q-values cibles (avec target network)
        with torch.no_grad():
            next_q = self.target_net(next_states_batch).squeeze()
            target_q = rewards_batch + (1 - dones_batch) * self.gamma * next_q
        
        # Loss et backprop
        loss = self.criterion(current_q, target_q)
        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()
        
        # Mise à jour du target network
        self.train_step_counter += 1
        if self.train_step_counter % self.target_update_freq == 0:
            self.target_net.load_state_dict(self.policy_net.state_dict())
    
    def _update_tabular(self, states, action_idx, reward, next_states, done):
        """Mise à jour Q-Learning tabulaire."""
        state = states[action_idx]
        state_hash = self._hash_state(state)
        
        # Q-value actuelle
        current_q = self.q_table.get(state_hash, 0.0)
        
        # Q-value cible
        if done or next_states is None:
            target_q = reward
        else:
            next_state = next_states[action_idx]
            next_state_hash = self._hash_state(next_state)
            next_q = self.q_table.get(next_state_hash, 0.0)
            target_q = reward + self.gamma * next_q
        
        # Mise à jour
        self.q_table[state_hash] = current_q + self.learning_rate * (target_q - current_q)
    
    def save_model(self, path: Optional[str] = None):
        """Sauvegarde le modèle entraîné."""
        save_path = path or self.model_path
        
        if self.use_dqn:
            torch.save({
                'policy_net': self.policy_net.state_dict(),
                'target_net': self.target_net.state_dict(),
                'optimizer': self.optimizer.state_dict(),
                'epsilon': self.epsilon,
                'train_step': self.train_step_counter
            }, save_path)
            print(f"✅ Modèle DQN sauvegardé: {save_path}")
        else:
            with open(save_path.replace('.pth', '.pkl'), 'wb') as f:
                pickle.dump({
                    'q_table': self.q_table,
                    'epsilon': self.epsilon
                }, f)
            print(f"✅ Q-table sauvegardée: {save_path.replace('.pth', '.pkl')}")
    
    def load_model(self, path: Optional[str] = None):
        """Charge un modèle pré-entraîné."""
        load_path = path or self.model_path
        
        if self.use_dqn:
            if os.path.exists(load_path):
                checkpoint = torch.load(load_path, map_location=self.device)
                self.policy_net.load_state_dict(checkpoint['policy_net'])
                self.target_net.load_state_dict(checkpoint['target_net'])
                self.optimizer.load_state_dict(checkpoint['optimizer'])
                self.epsilon = checkpoint.get('epsilon', self.epsilon_min)
                self.train_step_counter = checkpoint.get('train_step', 0)
                print(f"✅ Modèle DQN chargé: {load_path}")
                return True
        else:
            pkl_path = load_path.replace('.pth', '.pkl')
            if os.path.exists(pkl_path):
                with open(pkl_path, 'rb') as f:
                    data = pickle.load(f)
                    self.q_table = data['q_table']
                    self.epsilon = data.get('epsilon', self.epsilon_min)
                print(f"✅ Q-table chargée: {pkl_path}")
                return True
        
        print(f"⚠️ Aucun modèle trouvé à {load_path}")
        return False
