# ia_scheduler_rl.py
"""
Scheduler Kubernetes avec Reinforcement Learning (DQN/Q-Learning).

Version RL du scheduler intelligent pour réseau 5G slicing.
Utilise un agent RL entraîné pour optimiser le placement des pods.
"""

import time
import os
import numpy as np
from kubernetes import client, config, watch
from kubernetes.client.rest import ApiException

from schedulers.rl_environment import KubernetesSchedulingEnv
from schedulers.rl_agent import RLSchedulerAgent


# Configuration RL
USE_TRAINED_MODEL = os.getenv('RL_USE_TRAINED_MODEL', 'true').lower() == 'true'
MODEL_PATH = os.getenv('RL_MODEL_PATH', 'rl_scheduler_model.pth')
TRAINING_MODE = os.getenv('RL_TRAINING_MODE', 'false').lower() == 'true'
DEBUG_MODE = os.getenv('RL_DEBUG', 'false').lower() == 'true'


def load_k8s_config():
    """Charge la configuration Kubernetes (in-cluster ou local)."""
    try:
        config.load_incluster_config()
        print("✓ Configuration in-cluster chargée")
    except config.ConfigException:
        config.load_kube_config()
        print("✓ Configuration locale (kubeconfig) chargée")


def schedule_pod_with_rl(
    v1_api: client.CoreV1Api,
    env: KubernetesSchedulingEnv,
    agent: RLSchedulerAgent,
    pod_name: str,
    pod_namespace: str,
    training: bool = False
) -> bool:
    """
    Place un pod sur un nœud en utilisant l'agent RL.
    
    Returns:
        True si succès, False sinon
    """
    try:
        # 1. Récupérer l'état initial de l'environnement
        states, node_names = env.reset(pod_name)
        
        print(f"\nScheduler RL pour pod: {pod_namespace}/{pod_name}")
        print(env.get_state_info(states, node_names))
        
        # 1.5 NOUVEAU: Filtrer les nœuds saturés (CPU > 60%)
        # Ceci permet au modèle pré-entraîné de respecter la charge CPU
        available_indices = []
        available_nodes = []
        available_states = []
        
        for i, (state, node) in enumerate(zip(states, node_names)):
            cpu_usage = state[1]  # index 1 = CPU usage
            if cpu_usage < 0.60:  # Seuil: 60% CPU
                available_indices.append(i)
                available_nodes.append(node)
                available_states.append(state)
        
        # Si tous les nœuds sont saturés, utiliser tous les nœuds (fallback)
        if len(available_nodes) == 0:
            print("⚠️  ATTENTION: Tous les nœuds sont saturés (>60% CPU), utilisation de tous les nœuds")
            available_indices = list(range(len(node_names)))
            available_nodes = node_names
            available_states = states
        else:
            print(f"✅ Nœuds disponibles après filtrage CPU: {len(available_nodes)}/{len(node_names)}")
            for i, (node, state) in enumerate(zip(node_names, states)):
                cpu_usage = state[1] * 100
                status = "✅ DISPONIBLE" if i in available_indices else "❌ SATURÉ"
                print(f"   {node}: CPU={cpu_usage:.1f}% {status}")
            states = np.array(available_states)
            node_names = available_nodes
        
        # 2. L'agent sélectionne un nœud parmi les nœuds non saturés
        node_idx, selected_node = agent.select_action(states, node_names, training=training)
        
        print(f"Nœud sélectionné par RL: {selected_node} (epsilon={agent.epsilon:.3f})")
        
        # 3. Tenter de placer le pod sur le nœud choisi
        success = bind_pod_to_node(v1_api, pod_name, pod_namespace, selected_node)
        
        if not success:
            return False
        
        # 4. Si en mode training, calculer la récompense et mettre à jour l'agent
        if training:
            # Récupérer le nouvel état après placement
            time.sleep(2)  # Attendre que le placement soit effectif
            next_states, _ = env.reset(pod_name)  # Re-scan de l'environnement
            
            # Calculer la récompense
            reward = env.calculate_reward(node_idx, states, node_names)
            
            print(f"Récompense: {reward:.2f}")
            
            # Mettre à jour l'agent
            agent.update(states, node_idx, reward, next_states, done=True)
        
        return True
    
    except Exception as e:
        print(f"Erreur lors du scheduling RL: {e}")
        return False


def bind_pod_to_node(
    v1_api: client.CoreV1Api,
    pod_name: str,
    pod_namespace: str,
    node_name: str
) -> bool:
    """
    Lie un pod à un nœud (binding Kubernetes).
    """
    try:
        # Méthode 1: Binding standard
        binding = client.V1Binding(
            api_version="v1",
            kind="Binding",
            metadata=client.V1ObjectMeta(name=pod_name, namespace=pod_namespace),
            target=client.V1ObjectReference(
                api_version="v1",
                kind="Node",
                name=node_name
            )
        )
        
        v1_api.create_namespaced_binding(
            namespace=pod_namespace,
            body=binding,
            _preload_content=False
        )
        
        print(f"SUCCESS (BINDING): {pod_namespace}/{pod_name} → {node_name}")
        return True
    
    except ApiException as e:
        # Fallback: Patch du pod
        if e.status == 501:
            try:
                body = {"spec": {"nodeName": node_name}}
                v1_api.patch_namespaced_pod(
                    name=pod_name,
                    namespace=pod_namespace,
                    body=body
                )
                print(f"SUCCESS (FALLBACK PATCH): {pod_namespace}/{pod_name} → {node_name}")
                return True
            except Exception as patch_error:
                print(f"FAILED (PATCH): {patch_error}")
                return False
        else:
            print(f"FAILED (BINDING): {e}")
            return False


def main_scheduler_loop():
    """
    Boucle principale du scheduler RL.
    """
    print("\n" + "="*60)
    print("Kubernetes RL Scheduler - Deep Reinforcement Learning")
    print("="*60)
    
    # Charger la config K8s
    load_k8s_config()
    v1_api = client.CoreV1Api()
    
    # Initialiser l'environnement RL
    env = KubernetesSchedulingEnv(v1_api)
    
    # Initialiser l'agent RL
    agent = RLSchedulerAgent(
        state_size=7,  # État enrichi: [latence, cpu, mem, nb_pods, fragmentation, affinity, bandwidth]
        use_dqn=True,  # Utiliser DQN si PyTorch disponible
        epsilon=0.01 if USE_TRAINED_MODEL else 1.0,  # Faible exploration si modèle chargé
        model_path=MODEL_PATH
    )
    
    # Charger le modèle pré-entraîné si disponible
    if USE_TRAINED_MODEL:
        agent.load_model()
    
    print(f"\n Configuration:")
    print(f"  - Mode: {'🎓 Training' if TRAINING_MODE else '🎯 Inference'}")
    print(f"  - Modèle: {MODEL_PATH}")
    print(f"  - Epsilon: {agent.epsilon:.3f}")
    
    # Watcher pour surveiller les pods en attente
    w = watch.Watch()
    
    SCHEDULER_NAME = 'custom-ia-scheduler-rl'  # Nom du scheduler RL
    print(f"\n👀 En attente de pods à scheduler (schedulerName={SCHEDULER_NAME})...\n")
    
    try:
        for event in w.stream(v1_api.list_pod_for_all_namespaces, timeout_seconds=0):
            pod = event['object']
            event_type = event['type']
            
            if DEBUG_MODE:
                print(f"🔍 Event: {event_type} - Pod: {pod.metadata.namespace}/{pod.metadata.name} - Phase: {pod.status.phase} - Scheduler: {pod.spec.scheduler_name}")
            
            # Filtrer: uniquement les pods Pending avec notre schedulerName
            if (event_type == 'ADDED' and 
                pod.status.phase == 'Pending' and
                pod.spec.scheduler_name == SCHEDULER_NAME and
                not pod.spec.node_name):
                
                pod_name = pod.metadata.name
                pod_namespace = pod.metadata.namespace
                
                print(f"\n📦 Nouveau pod détecté: {pod_namespace}/{pod_name}")
                
                # Scheduler le pod avec RL
                schedule_pod_with_rl(
                    v1_api,
                    env,
                    agent,
                    pod_name,
                    pod_namespace,
                    training=TRAINING_MODE
                )
                
                # Sauvegarder le modèle périodiquement en mode training
                if TRAINING_MODE and agent.train_step_counter % 50 == 0:
                    agent.save_model()
                    print(f"💾 Modèle sauvegardé (step {agent.train_step_counter})")
    
    except KeyboardInterrupt:
        print("\n\n⏸ Arrêt du scheduler...")
        if TRAINING_MODE:
            agent.save_model()
            print(" Modèle final sauvegardé")
    
    except Exception as e:
        print(f"\n Erreur critique: {e}")
        if TRAINING_MODE:
            agent.save_model()


if __name__ == "__main__":
    main_scheduler_loop()
