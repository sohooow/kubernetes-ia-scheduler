# ia_scheduler.py (VERSION ULTIME - Correction du Patching/Binding)

from kubernetes import client, config, watch
import time
from scoring_logic import calculate_score_and_select_node 

SCHEDULER_NAME = "custom-ia-scheduler"

def schedule_pod(pod_name: str, namespace: str, node_name: str):
    """
    Assigne (bind) le pod au nœud choisi en utilisant la méthode V1Binding officielle.
    """
    v1 = client.CoreV1Api()
    
    # Création de l'objet V1ObjectReference pour la cible (le Node)
    target = client.V1ObjectReference(api_version="v1", kind="Node", name=node_name)
    
    # Création du corps de la requête V1Binding
    binding_body = client.V1Binding(
        api_version='v1',
        kind='Binding',
        metadata=client.V1ObjectMeta(name=pod_name),
        target=target
    )
    
    try:
        # Tente la méthode de binding standard (sans argument 'name')
        v1.create_namespaced_binding(
            namespace=namespace, 
            body=binding_body
        )
        print(f"\n✅ SUCCESS: Pod {pod_name} dans {namespace} assigné à {node_name}.")
    except Exception as e:
        # Beaucoup d'installations/versions du client K8s lèvent des erreurs
        # au moment de construire/appeler le Binding (validation côté client).
        # Dans ce cas on tombe back sur un patch du pod (nodeName) qui marche
        # généralement mieux en pratique.
        print(f"Binding échoué ({type(e).__name__}: {e}), tentative de fallback par patch...")

        patch_body = {"spec": {"nodeName": node_name}}

        try:
            # La méthode de patching nécessite parfois un content_type spécifique,
            # mais l'appel simple fonctionne dans la plupart des cas.
            v1.patch_namespaced_pod(
                name=pod_name,
                namespace=namespace, 
                body=patch_body
            )
            print(f"\n✅ SUCCESS (FALLBACK PATCH): Pod {pod_name} assigné à {node_name}.")
        except client.ApiException as e2:
            # Erreur d'API lors du patch : afficher le code si disponible
            status = getattr(e2, 'status', 'unknown')
            print(f"❌ ERREUR FINALE: Échec du Patch (Code: {status}). Le pod est bloqué. Exception: {e2}")
        except Exception as e3:
            print(f"❌ ERREUR FINALE: Échec du Patch (erreur inattendue): {e3}")


def main():
    print(f"Démarrage du Scheduler IA ({SCHEDULER_NAME})...")
    
    try:
        # Tente d'abord de charger la config in-cluster (pour un pod dans K8s)
        config.load_incluster_config()
        print("✓ Configuration in-cluster chargée (running inside Kubernetes)")
    except config.ConfigException:
        # Sinon, charge la config locale (pour exécution locale)
        try:
            config.load_kube_config()
            print("✓ Configuration locale (~/.kube/config) chargée")
        except Exception as e:
            print(f"Erreur de configuration K8s: {e}")
            return

    v1 = client.CoreV1Api()
    w = watch.Watch()
    
    while True:
        try:
            print(f"En attente de nouveaux pods avec schedulerName={SCHEDULER_NAME}...")
            
            for event in w.stream(v1.list_pod_for_all_namespaces, timeout_seconds=300):
                pod = event['object']
                
                is_pending = pod.status.phase == "Pending"
                wants_our_scheduler = pod.spec.scheduler_name == SCHEDULER_NAME
                is_unassigned = not pod.spec.node_name
                
                if is_pending and wants_our_scheduler and is_unassigned:
                    print(f"\n👀 Pod non assigné trouvé: {pod.metadata.name} (Namespace: {pod.metadata.namespace})")
                    
                    best_node = calculate_score_and_select_node(v1, pod.metadata.name)
                    
                    if best_node:
                        schedule_pod(pod.metadata.name, pod.metadata.namespace, best_node)
                    else:
                        print(f"⚠️ Aucun nœud optimal trouvé pour le pod {pod.metadata.name}. Le laisser en attente.")

        except client.ApiException as e:
            print(f"Erreur d'API K8s (reconnexion dans 5s): {e}")
            time.sleep(5)
        except Exception as e:
            print(f"❌ Erreur inattendue (reconnexion dans 10s): {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()