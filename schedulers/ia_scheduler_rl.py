"""
Scheduler Kubernetes avec Reinforcement Learning (DQN/Q-Learning).
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
DEBUG_MODE = os.getenv('RL_DEBUG', 'true').lower() == 'true'

# IMPORTANT: Doit correspondre au champ schedulerName dans vos YAMLs
SCHEDULER_NAME = 'ia-scheduler'

def load_k8s_config():
    try:
        config.load_incluster_config()
        print("✓ Configuration in-cluster chargée")
    except config.ConfigException:
        config.load_kube_config()
        print("✓ Configuration locale (kubeconfig) chargée")

def schedule_pod_with_rl(v1_api, env, agent, pod_name, pod_namespace, training=False):
    try:
        # 1. Récupérer l'état
        states, node_names = env.reset(pod_name)
        
        if not node_names:
            print(f"❌ ERREUR: Aucun nœud candidat trouvé pour {pod_name}!")
            return False

        print(f"\n--- Scheduling {pod_name} ---")
        
        # 2. Filtrage simple (CPU < 80%)
        # On simplifie le filtrage pour éviter de bloquer si tout est un peu chargé
        available_indices = []
        for i, state in enumerate(states):
            # state[1] est le CPU usage normalisé
            if state[1] < 0.80: 
                available_indices.append(i)
        
        # Fallback: Si tout est saturé, on prend tout
        if not available_indices:
            print("⚠️ Tous les nœuds chargés > 80%, mode dégradé activé.")
            available_indices = list(range(len(node_names)))

        # 3. Sélection Action via Agent
        # L'agent décide sur quel index (parmi tous les nœuds) il veut aller
        node_idx, selected_node = agent.select_action(states, node_names, training=training)
        
        # Si l'agent choisit un nœud saturé alors qu'il y a mieux, on pourrait forcer, 
        # mais pour le RL on le laisse faire ses erreurs (ou ses réussites).
        
        print(f"🤖 Décision IA: {selected_node}")
        
        # 4. Binding
        return bind_pod_to_node(v1_api, pod_name, pod_namespace, selected_node)

    except Exception as e:
        print(f"❌ Exception dans schedule_pod_with_rl: {e}")
        return False

def bind_pod_to_node(v1_api, pod_name, pod_namespace, node_name):
    try:
        target = client.V1ObjectReference(kind="Node", api_version="v1", name=node_name)
        meta = client.V1ObjectMeta(name=pod_name)        
        body = client.V1Binding(api_version="v1", kind="Binding", metadata=meta, target=target)
        
        v1_api.create_namespaced_binding(namespace=pod_namespace, body=body)
        print(f"✅ SUCCÈS: {pod_name} -> {node_name}")
        return True
    except ApiException as e:
        print(f"⚠️ Échec Binding standard ({e.status}), essai Patch...")
        try:
            # Fallback Patch
            body = {"spec": {"nodeName": node_name}}
            v1_api.patch_namespaced_pod(name=pod_name, namespace=pod_namespace, body=body)
            print(f"✅ SUCCÈS (Patch): {pod_name} -> {node_name}")
            return True
        except Exception as e2:
            print(f"❌ ÉCHEC TOTAL pour {pod_name}: {e2}")
            return False

def main_scheduler_loop():
    print("\n" + "="*60)
    print(f"🚀 Démarrage Scheduler IA: '{SCHEDULER_NAME}'")
    print("="*60)
    
    load_k8s_config()
    v1_api = client.CoreV1Api()
    
    # Test de connexion et vérification des nœuds
    try:
        nodes = v1_api.list_node()
        print(f"✓ Connecté à l'API K8s. {len(nodes.items)} nœuds détectés.")
        for n in nodes.items:
            print(f"  - {n.metadata.name} (Roles: {n.metadata.labels.get('kubernetes.io/role', 'agent')})")
    except Exception as e:
        print(f"❌ Impossible de lister les nœuds: {e}")
        return

    env = KubernetesSchedulingEnv(v1_api)
    # Agent simplifié pour garantir le fonctionnement sans modèle
    agent = RLSchedulerAgent(state_size=7, use_dqn=True, model_path=MODEL_PATH)
    
    # Essai de chargement, sinon initialisation à zéro
    if USE_TRAINED_MODEL:
        agent.load_model()

    w = watch.Watch()
    print(f"\n🎧 En écoute des pods Pending avec schedulerName='{SCHEDULER_NAME}'...")
    
    try:
        for event in w.stream(v1_api.list_pod_for_all_namespaces, timeout_seconds=0):
            pod = event['object']
            
            if (pod.status.phase == 'Pending' and 
                pod.spec.scheduler_name == SCHEDULER_NAME and 
                pod.spec.node_name is None):
                
                print(f"\n⚡ Pod détecté: {pod.metadata.name}")
                schedule_pod_with_rl(v1_api, env, agent, pod.metadata.name, pod.metadata.namespace, training=TRAINING_MODE)
                
    except KeyboardInterrupt:
        print("Arrêt.")
    except Exception as e:
        print(f"Erreur critique boucle: {e}")

if __name__ == "__main__":
    main_scheduler_loop()