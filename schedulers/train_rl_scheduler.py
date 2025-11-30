# train_rl_scheduler.py
import numpy as np
import matplotlib.pyplot as plt
from typing import List, Tuple
from kubernetes import client, config
from schedulers.rl_environment import KubernetesSchedulingEnv
from schedulers.rl_agent import RLSchedulerAgent

def load_k8s_config():
    """Charge la configuration Kubernetes."""
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()

def simulate_episode(env, agent, num_pods=10):
    total_reward = 0.0
    # Reset environnement
    states, node_names = env.reset("training")
    
    for i in range(num_pods):
        # 1. Action
        node_idx, _ = agent.select_action(states, node_names, training=True)
        
        # 2. Récompense
        reward = env.calculate_reward(node_idx, states, node_names)
        
        # 3. Apprentissage
        agent.update(states, node_idx, reward, states, done=(i==num_pods-1))
        
        total_reward += reward
        
    return total_reward

def plot_training_results(rewards, epsilons, save_path="TESTS/RESULTS/training_results.png"):
    """Génère le graphique de convergence."""
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8))
    
    # Courbe de récompense
    ax1.plot(rewards, color='blue', alpha=0.3, label='Reward brut')
    # Moyenne mobile pour lisser
    window = 20
    if len(rewards) >= window:
        avg_rewards = np.convolve(rewards, np.ones(window)/window, mode='valid')
        ax1.plot(range(window-1, len(rewards)), avg_rewards, color='red', linewidth=2, label='Moyenne mobile')
    
    ax1.set_title('Convergence de l\'Agent (Optimisation Latence)')
    ax1.set_ylabel('Récompense Totale')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # Courbe d'exploration
    ax2.plot(epsilons, color='green', label='Epsilon')
    ax2.set_title('Taux d\'Exploration')
    ax2.set_ylabel('Epsilon')
    ax2.set_xlabel('Épisode')
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(save_path)
    print(f"📊 Graphique d'entraînement sauvegardé : {save_path}")

def train_rl_agent(num_episodes=200):
    print("🚀 Démarrage Entraînement LATENCE PURE (avec visualisation)...")
    load_k8s_config()
    v1 = client.CoreV1Api()
    env = KubernetesSchedulingEnv(v1)
    
    # Agent configuré pour converger vite
    agent = RLSchedulerAgent(
        state_size=7, 
        use_dqn=True,
        learning_rate=0.001, 
        gamma=0.90,
        epsilon=1.0, 
        epsilon_min=0.01, 
        epsilon_decay=0.97, # Décroissance rapide pour voir le résultat vite
        model_path="rl_scheduler_model.pth"
    )
    
    all_rewards = []
    all_epsilons = []
    
    try:
        for ep in range(num_episodes):
            reward = simulate_episode(env, agent, num_pods=10)
            
            all_rewards.append(reward)
            all_epsilons.append(agent.epsilon)
            
            if (ep+1) % 50 == 0:
                avg = np.mean(all_rewards[-50:])
                print(f"Ep {ep+1}/{num_episodes} | Avg Reward: {avg:.1f} | Epsilon: {agent.epsilon:.2f}")
                agent.save_model()
                
    except KeyboardInterrupt:
        print("\nArrêt manuel.")
    
    # Sauvegarde finale
    agent.save_model()
    print("✅ Modèle sauvegardé.")
    
    # Génération du graphique
    plot_training_results(all_rewards, all_epsilons)

if __name__ == "__main__":
    train_rl_agent()