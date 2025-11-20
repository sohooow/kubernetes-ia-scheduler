# train_rl_scheduler.py
"""
Script d'entraînement du scheduler RL par simulation.

Génère des scénarios de placement de pods pour entraîner l'agent RL
avant déploiement en production.
"""

import numpy as np
import random
from kubernetes import client, config
from schedulers.rl_environment import KubernetesSchedulingEnv
from schedulers.rl_agent import RLSchedulerAgent
import matplotlib.pyplot as plt
from typing import List, Tuple


def load_k8s_config():
    """Charge la configuration Kubernetes."""
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()


def simulate_pod_placement_episode(
    env: KubernetesSchedulingEnv,
    agent: RLSchedulerAgent,
    num_pods: int = 10
) -> Tuple[float, List[float]]:
    """
    Simule le placement de plusieurs pods pour un épisode d'entraînement.
    
    Returns:
        (reward_total, rewards_per_pod)
    """
    total_reward = 0.0
    rewards_per_pod = []
    
    for i in range(num_pods):
        # Reset l'environnement pour un nouveau pod
        states, node_names = env.reset(f"training-pod-{i}")
        
        # Agent sélectionne un nœud (training mode = epsilon-greedy)
        node_idx, selected_node = agent.select_action(states, node_names, training=True)
        
        # Calculer la récompense
        reward = env.calculate_reward(node_idx, states, node_names)
        
        # Simuler l'impact du placement sur l'environnement
        # (augmenter artificiellement la charge du nœud sélectionné)
        states[node_idx][1] += 0.05  # +5% CPU
        states[node_idx][2] += 0.03  # +3% Memory
        states[node_idx][3] += 0.02  # +1 pod (normalisé)
        
        # Mettre à jour l'agent
        agent.update(states, node_idx, reward, states, done=False)
        
        total_reward += reward
        rewards_per_pod.append(reward)
    
    return total_reward, rewards_per_pod


def train_rl_agent(
    num_episodes: int = 500,
    pods_per_episode: int = 10,
    model_save_path: str = "rl_scheduler_model.pth",
    plot_results: bool = True
):
    """
    Entraîne l'agent RL par simulation.
    
    Args:
        num_episodes: Nombre d'épisodes d'entraînement
        pods_per_episode: Nombre de pods à placer par épisode
        model_save_path: Chemin de sauvegarde du modèle
        plot_results: Afficher les courbes d'apprentissage
    """
    print("\n" + "="*70)
    print("🎓 TRAINING RL SCHEDULER - Deep Reinforcement Learning")
    print("="*70)
    
    # Charger la config K8s
    load_k8s_config()
    v1_api = client.CoreV1Api()
    
    # Initialiser environnement et agent
    env = KubernetesSchedulingEnv(v1_api)
    agent = RLSchedulerAgent(
        state_size=7,  # État enrichi: latence, CPU, mémoire, nb_pods, fragmentation, affinity, bandwidth
        use_dqn=True,
        learning_rate=0.001,
        gamma=0.95,
        epsilon=1.0,  # Exploration maximale au début
        epsilon_min=0.01,
        epsilon_decay=0.995,
        model_path=model_save_path
    )
    
    print(f"\n📊 Configuration:")
    print(f"  - Épisodes: {num_episodes}")
    print(f"  - Pods par épisode: {pods_per_episode}")
    print(f"  - Algorithme: {'DQN' if agent.use_dqn else 'Q-Learning tabulaire'}")
    print(f"  - Learning rate: 0.001")
    print(f"  - Gamma: 0.95")
    print(f"  - Epsilon: {agent.epsilon} → {agent.epsilon_min}")
    
    # Historique d'entraînement
    episode_rewards = []
    episode_epsilons = []
    moving_avg_rewards = []
    
    print("\n🚀 Démarrage de l'entraînement...\n")
    
    try:
        for episode in range(num_episodes):
            # Simuler un épisode de placement de pods
            total_reward, _ = simulate_pod_placement_episode(
                env, agent, num_pods=pods_per_episode
            )
            
            episode_rewards.append(total_reward)
            episode_epsilons.append(agent.epsilon)
            
            # Calcul de la moyenne mobile (sur 50 épisodes)
            if len(episode_rewards) >= 50:
                moving_avg = np.mean(episode_rewards[-50:])
            else:
                moving_avg = np.mean(episode_rewards)
            moving_avg_rewards.append(moving_avg)
            
            # Affichage périodique
            if (episode + 1) % 50 == 0:
                print(f"Episode {episode+1}/{num_episodes} | "
                      f"Reward: {total_reward:.2f} | "
                      f"Avg(50): {moving_avg:.2f} | "
                      f"Epsilon: {agent.epsilon:.3f}")
                
                # Sauvegarde intermédiaire
                agent.save_model()
        
        # Sauvegarde finale
        agent.save_model()
        print(f"\n✅ Entraînement terminé !")
        print(f"💾 Modèle sauvegardé: {model_save_path}")
        
        # Afficher les courbes d'apprentissage
        if plot_results:
            plot_training_results(
                episode_rewards, 
                moving_avg_rewards, 
                episode_epsilons,
                save_path="training_results.png"
            )
    
    except KeyboardInterrupt:
        print("\n\n⏸️  Entraînement interrompu par l'utilisateur")
        agent.save_model()
        print(f"💾 Modèle sauvegardé: {model_save_path}")


def plot_training_results(
    episode_rewards: List[float],
    moving_avg_rewards: List[float],
    episode_epsilons: List[float],
    save_path: str = "training_results.png"
):
    """
    Affiche et sauvegarde les graphiques d'apprentissage.
    """
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10))
    
    episodes = range(1, len(episode_rewards) + 1)
    
    # Graphique 1: Récompenses
    ax1.plot(episodes, episode_rewards, alpha=0.3, label='Reward par épisode', color='blue')
    ax1.plot(episodes, moving_avg_rewards, label='Moyenne mobile (50 épisodes)', 
             color='red', linewidth=2)
    ax1.set_xlabel('Épisode')
    ax1.set_ylabel('Récompense totale')
    ax1.set_title('Évolution de la récompense durant l\'entraînement')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # Graphique 2: Epsilon (exploration)
    ax2.plot(episodes, episode_epsilons, label='Epsilon (exploration)', color='green')
    ax2.set_xlabel('Épisode')
    ax2.set_ylabel('Epsilon')
    ax2.set_title('Décroissance de l\'exploration (epsilon-greedy)')
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(save_path, dpi=300, bbox_inches='tight')
    print(f"📊 Graphiques sauvegardés: {save_path}")
    
    # Afficher si en local
    try:
        plt.show()
    except:
        pass


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Entraînement du scheduler RL")
    parser.add_argument('--episodes', type=int, default=500, 
                       help='Nombre d\'épisodes d\'entraînement')
    parser.add_argument('--pods-per-episode', type=int, default=10,
                       help='Nombre de pods par épisode')
    parser.add_argument('--model-path', type=str, default='rl_scheduler_model.pth',
                       help='Chemin de sauvegarde du modèle')
    parser.add_argument('--no-plot', action='store_true',
                       help='Désactiver l\'affichage des graphiques')
    
    args = parser.parse_args()
    
    train_rl_agent(
        num_episodes=args.episodes,
        pods_per_episode=args.pods_per_episode,
        model_save_path=args.model_path,
        plot_results=not args.no_plot
    )
