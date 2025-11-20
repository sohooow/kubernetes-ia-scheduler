# benchmark_schedulers.py
"""
Benchmark comparatif des 3 schedulers:
1. kube-scheduler (default)
2. Heuristique pondérée (scoring_logic.py)
3. Reinforcement Learning (DQN/Q-Learning)

Mesure: latence, CPU, mémoire, distribution des pods.
"""

import time
import numpy as np
import matplotlib.pyplot as plt
from kubernetes import client, config
from typing import Dict, List, Tuple
import subprocess
import json


def load_k8s_config():
    """Charge la configuration Kubernetes."""
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()


def deploy_test_workload(
    scheduler_name: str,
    num_replicas: int = 10,
    deployment_name: str = "benchmark-test"
) -> str:
    """
    Déploie une charge de travail de test avec un scheduler spécifié.
    
    Returns:
        Nom du deployment créé
    """
    # Créer un manifest temporaire
    manifest = f"""
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {deployment_name}-{scheduler_name.replace(' ', '-').lower()}
  labels:
    benchmark: "true"
    scheduler-type: {scheduler_name}
spec:
  replicas: {num_replicas}
  selector:
    matchLabels:
      app: {deployment_name}
      scheduler-type: {scheduler_name}
  template:
    metadata:
      labels:
        app: {deployment_name}
        scheduler-type: {scheduler_name}
    spec:
      schedulerName: {scheduler_name}
      containers:
      - name: test-workload
        image: nginx:alpine
        resources:
          requests:
            cpu: 100m
            memory: 64Mi
          limits:
            cpu: 200m
            memory: 128Mi
"""
    
    # Écrire le manifest
    manifest_file = f"/tmp/{deployment_name}_{scheduler_name}.yaml"
    with open(manifest_file, 'w') as f:
        f.write(manifest)
    
    # Appliquer
    subprocess.run(['kubectl', 'apply', '-f', manifest_file], check=True)
    
    deployment_full_name = f"{deployment_name}-{scheduler_name.replace(' ', '-').lower()}"
    print(f"✅ Deployment créé: {deployment_full_name}")
    
    return deployment_full_name


def wait_for_pods_ready(deployment_name: str, timeout: int = 120) -> bool:
    """
    Attend que tous les pods d'un deployment soient Ready.
    
    Returns:
        True si tous les pods sont ready, False si timeout
    """
    v1_api = client.CoreV1Api()
    apps_v1 = client.AppsV1Api()
    
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        try:
            deployment = apps_v1.read_namespaced_deployment(
                name=deployment_name,
                namespace='default'
            )
            
            ready = deployment.status.ready_replicas or 0
            desired = deployment.spec.replicas
            
            if ready == desired:
                return True
            
            time.sleep(2)
        
        except Exception as e:
            print(f"Erreur lors de la vérification: {e}")
            time.sleep(2)
    
    return False


def collect_metrics(deployment_name: str) -> Dict[str, any]:
    """
    Collecte les métriques pour un deployment:
    - Distribution des pods par nœud
    - Latence moyenne (basée sur les labels des nœuds)
    - Usage CPU/mémoire
    """
    v1_api = client.CoreV1Api()
    
    # Récupérer les pods du deployment
    pods = v1_api.list_namespaced_pod(
        namespace='default',
        label_selector=f"app=benchmark-test"
    ).items
    
    pods = [p for p in pods if deployment_name in p.metadata.name]
    
    # Distribution par nœud
    node_distribution = {}
    latencies = []
    total_cpu = 0.0
    total_mem = 0.0
    
    for pod in pods:
        node_name = pod.spec.node_name
        if not node_name:
            continue
        
        # Compter les pods par nœud
        node_distribution[node_name] = node_distribution.get(node_name, 0) + 1
        
        # Récupérer la latence du nœud (via label)
        try:
            node_obj = v1_api.read_node(name=node_name)
            latency_type = node_obj.metadata.labels.get('type', 'standard')
            latency = 10.0 if latency_type == 'low-latency' else 50.0
            latencies.append(latency)
        except:
            latencies.append(50.0)
        
        # CPU/mémoire (requests)
        for container in pod.spec.containers:
            reqs = getattr(container.resources, 'requests', None) or {}
            cpu_req = reqs.get('cpu', '0')
            mem_req = reqs.get('memory', '0')
            
            # Parser CPU
            if str(cpu_req).endswith('m'):
                total_cpu += float(str(cpu_req)[:-1]) / 1000.0
            else:
                try:
                    total_cpu += float(cpu_req)
                except:
                    pass
            
            # Parser Mémoire
            mem_str = str(mem_req)
            if mem_str.endswith('Mi'):
                total_mem += float(mem_str[:-2])
    
    # Calculer la latence P95
    latencies_sorted = sorted(latencies)
    p95_idx = int(len(latencies_sorted) * 0.95)
    latency_p95 = latencies_sorted[p95_idx] if latencies_sorted else 0.0
    
    return {
        'num_pods': len(pods),
        'node_distribution': node_distribution,
        'latency_mean': np.mean(latencies) if latencies else 0.0,
        'latency_p95': latency_p95,
        'total_cpu_requested': total_cpu,
        'total_memory_requested': total_mem
    }


def cleanup_deployment(deployment_name: str):
    """Supprime un deployment."""
    subprocess.run(
        ['kubectl', 'delete', 'deployment', deployment_name, '--ignore-not-found=true'],
        check=False
    )
    print(f"🗑️  Deployment supprimé: {deployment_name}")


def run_benchmark(
    num_replicas: int = 10,
    schedulers: List[Tuple[str, str]] = None
):
    """
    Exécute le benchmark complet.
    
    Args:
        num_replicas: Nombre de replicas pour chaque test
        schedulers: Liste de (scheduler_name, display_name)
    """
    print("\n" + "="*70)
    print("📊 BENCHMARK COMPARATIF DES SCHEDULERS")
    print("="*70)
    
    load_k8s_config()
    
    if schedulers is None:
        schedulers = [
            ('default', 'kube-scheduler'),
            ('custom-ia-scheduler', 'Heuristique'),
            ('custom-ia-scheduler', 'RL-DQN')  # Même scheduler mais avec modèle RL
        ]
    
    results = {}
    
    for scheduler_name, display_name in schedulers:
        print(f"\n--- Test avec {display_name} ---")
        
        # Déployer la charge de test
        deployment = deploy_test_workload(
            scheduler_name=scheduler_name,
            num_replicas=num_replicas,
            deployment_name="benchmark-test"
        )
        
        # Attendre que les pods soient ready
        print(f"⏳ Attente des pods ({deployment})...")
        if not wait_for_pods_ready(deployment, timeout=120):
            print(f"⚠️  Timeout: tous les pods ne sont pas ready")
        else:
            print(f"✅ Tous les pods sont ready")
        
        # Attendre stabilisation
        time.sleep(10)
        
        # Collecter les métriques
        metrics = collect_metrics(deployment)
        results[display_name] = metrics
        
        print(f"\n📈 Résultats {display_name}:")
        print(f"  - Pods déployés: {metrics['num_pods']}")
        print(f"  - Distribution: {metrics['node_distribution']}")
        print(f"  - Latence moyenne: {metrics['latency_mean']:.1f}ms")
        print(f"  - Latence P95: {metrics['latency_p95']:.1f}ms")
        print(f"  - CPU total: {metrics['total_cpu_requested']:.2f} cores")
        
        # Nettoyer
        cleanup_deployment(deployment)
        time.sleep(5)
    
    # Générer les graphiques comparatifs
    plot_comparison(results, num_replicas)
    
    return results


def plot_comparison(results: Dict[str, Dict], num_replicas: int):
    """
    Génère les graphiques comparatifs.
    """
    schedulers = list(results.keys())
    
    # Données à comparer
    latencies_mean = [results[s]['latency_mean'] for s in schedulers]
    latencies_p95 = [results[s]['latency_p95'] for s in schedulers]
    cpu_total = [results[s]['total_cpu_requested'] for s in schedulers]
    
    # Créer les graphiques
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    
    # Graphique 1: Latence moyenne
    axes[0, 0].bar(schedulers, latencies_mean, color=['#1f77b4', '#ff7f0e', '#2ca02c'])
    axes[0, 0].set_ylabel('Latence (ms)')
    axes[0, 0].set_title('Latence moyenne')
    axes[0, 0].grid(axis='y', alpha=0.3)
    
    # Graphique 2: Latence P95
    axes[0, 1].bar(schedulers, latencies_p95, color=['#1f77b4', '#ff7f0e', '#2ca02c'])
    axes[0, 1].set_ylabel('Latence P95 (ms)')
    axes[0, 1].set_title('Latence P95 (percentile 95)')
    axes[0, 1].grid(axis='y', alpha=0.3)
    
    # Graphique 3: Distribution des pods
    ax3 = axes[1, 0]
    x = np.arange(len(schedulers))
    width = 0.2
    
    # Récupérer les nœuds uniques
    all_nodes = set()
    for s in schedulers:
        all_nodes.update(results[s]['node_distribution'].keys())
    all_nodes = sorted(all_nodes)
    
    for i, node in enumerate(all_nodes):
        counts = [results[s]['node_distribution'].get(node, 0) for s in schedulers]
        ax3.bar(x + i*width, counts, width, label=node)
    
    ax3.set_ylabel('Nombre de pods')
    ax3.set_title('Distribution des pods par nœud')
    ax3.set_xticks(x + width)
    ax3.set_xticklabels(schedulers)
    ax3.legend()
    ax3.grid(axis='y', alpha=0.3)
    
    # Graphique 4: CPU total
    axes[1, 1].bar(schedulers, cpu_total, color=['#1f77b4', '#ff7f0e', '#2ca02c'])
    axes[1, 1].set_ylabel('CPU total (cores)')
    axes[1, 1].set_title('Ressources CPU demandées')
    axes[1, 1].grid(axis='y', alpha=0.3)
    
    plt.tight_layout()
    plt.savefig('scheduler_comparison.png', dpi=300, bbox_inches='tight')
    print(f"\n📊 Graphiques sauvegardés: scheduler_comparison.png")
    
    try:
        plt.show()
    except:
        pass


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Benchmark des schedulers Kubernetes")
    parser.add_argument('--replicas', type=int, default=10,
                       help='Nombre de replicas par test')
    
    args = parser.parse_args()
    
    run_benchmark(num_replicas=args.replicas)
