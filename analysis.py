import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import requests
from typing import Dict, Tuple, Optional
from datetime import datetime
import logging

# Configuration du logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration de style pour les graphiques
plt.style.use('seaborn-v0_8-darkgrid')
sns.set_palette("husl")

# --- 1. CONFIGURATION ---
PROMETHEUS_URL = "http://127.0.0.1:9090"

TIME_RANGES = {
    'S1 - Base (Défaut)': (1763324504, 1763324715),
    'S2 - IA Latence': (1763324762, 1763324903),
    'S3 - IA Charge': (1763325107, 1763325250),
}

# Métriques multiples pour une analyse plus complète
METRICS = {
    'cpu': '100 * (1 - avg(rate(node_cpu_seconds_total{mode="idle"}[1m])) by (instance))',
    'memory': '100 * (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes))',
    'network_receive': 'rate(node_network_receive_bytes_total[1m])',
}

LATENCY_P95_MS = {
    'S1 - Base (Défaut)': 30,
    'S2 - IA Latence': 12,
    'S3 - IA Charge': 45,
}


class PrometheusAnalyzer:
    """Classe principale pour l'analyse des métriques Prometheus."""
    
    def __init__(self, prometheus_url: str):
        self.prometheus_url = prometheus_url
        self.verify_connection()
    
    def verify_connection(self) -> bool:
        """Vérifie la connexion à Prometheus."""
        try:
            response = requests.get(f'{self.prometheus_url}/api/v1/query', 
                                   params={'query': 'up'}, 
                                   timeout=5)
            response.raise_for_status()
            logger.info("✓ Connexion à Prometheus établie")
            return True
        except Exception as e:
            logger.error(f"✗ Impossible de se connecter à Prometheus: {e}")
            return False
    
    def query_range(self, query: str, start_time: int, end_time: int, 
                   step: str = '15s') -> pd.DataFrame:
        """Interroge Prometheus et retourne un DataFrame structuré."""
        params = {
            'query': query,
            'start': start_time,
            'end': end_time,
            'step': step
        }
        
        try:
            response = requests.get(f'{self.prometheus_url}/api/v1/query_range', 
                                   params=params, timeout=15)
            response.raise_for_status()
            data = response.json().get('data', {}).get('result', [])
            
            if not data:
                logger.warning(f"Aucune donnée retournée pour la requête: {query[:50]}...")
                return pd.DataFrame()
            
            all_series = []
            for series in data:
                node = self._extract_node_name(series['metric'].get('instance', ''))
                for timestamp, value in series['values']:
                    all_series.append({
                        'timestamp': pd.to_datetime(timestamp, unit='s'),
                        'node': node,
                        'value': float(value)
                    })
            
            df = pd.DataFrame(all_series)
            if not df.empty:
                df = df.pivot_table(index='timestamp', columns='node', values='value')
                worker_nodes = [col for col in df.columns if 'worker' in col.lower()]
                if worker_nodes:
                    df = df[worker_nodes]
            
            return df
            
        except Exception as e:
            logger.error(f"Erreur lors de l'extraction: {e}")
            return pd.DataFrame()
    
    @staticmethod
    def _extract_node_name(instance: str) -> str:
        """Extrait le nom du nœud depuis l'instance."""
        if not instance:
            return 'unknown'
        return instance.split(':')[0].split('.')[-1]


class LoadBalanceAnalyzer:
    """Analyse l'équilibrage de charge et calcule les métriques."""
    
    @staticmethod
    def calculate_variance(df: pd.DataFrame) -> float:
        """Calcule l'écart-type moyen (variance) de l'utilisation."""
        if df.empty:
            return np.nan
        return df.std(axis=1).mean()
    
    @staticmethod
    def calculate_coefficient_variation(df: pd.DataFrame) -> float:
        """Calcule le coefficient de variation (CV = std/mean * 100)."""
        if df.empty:
            return np.nan
        mean_values = df.mean(axis=1)
        std_values = df.std(axis=1)
        cv = (std_values / mean_values * 100).mean()
        return cv
    
    @staticmethod
    def calculate_imbalance_score(df: pd.DataFrame) -> float:
        """Score de déséquilibre: différence max-min moyenne."""
        if df.empty:
            return np.nan
        return (df.max(axis=1) - df.min(axis=1)).mean()
    
    @staticmethod
    def get_statistics(df: pd.DataFrame) -> Dict:
        """Calcule des statistiques complètes."""
        if df.empty:
            return {}
        
        return {
            'mean_usage': df.mean().mean(),
            'max_usage': df.max().max(),
            'min_usage': df.min().min(),
            'variance': LoadBalanceAnalyzer.calculate_variance(df),
            'cv': LoadBalanceAnalyzer.calculate_coefficient_variation(df),
            'imbalance': LoadBalanceAnalyzer.calculate_imbalance_score(df)
        }


class Visualizer:
    """Classe pour générer les visualisations."""
    
    @staticmethod
    def plot_comprehensive_analysis(results: Dict, variance_data: Dict, latency_data: Dict):
        """Crée un dashboard complet avec tous les graphiques."""
        fig = plt.figure(figsize=(16, 10))
        gs = fig.add_gridspec(3, 2, hspace=0.3, wspace=0.3)
        
        # 1. Latence P95
        ax1 = fig.add_subplot(gs[0, 0])
        Visualizer._plot_latency(ax1, latency_data)
        
        # 2. Variance CPU
        ax2 = fig.add_subplot(gs[0, 1])
        Visualizer._plot_variance(ax2, variance_data)
        
        # 3. Évolution temporelle CPU
        ax3 = fig.add_subplot(gs[1, :])
        Visualizer._plot_temporal_cpu(ax3, results)
        
        # 4. Comparaison multi-métriques
        ax4 = fig.add_subplot(gs[2, 0])
        Visualizer._plot_multimetric_comparison(ax4, results)
        
        # 5. Score de déséquilibre
        ax5 = fig.add_subplot(gs[2, 1])
        Visualizer._plot_imbalance_score(ax5, results)
        
        plt.suptitle('Analyse Complète de l\'Équilibrage de Charge IA', 
                    fontsize=16, fontweight='bold', y=0.995)
        plt.savefig('prometheus_analysis_complete.png', dpi=300, bbox_inches='tight')
        plt.show()
    
    @staticmethod
    def _plot_latency(ax, latency_data):
        """Graphique de latence."""
        scenarios = list(latency_data.keys())
        values = list(latency_data.values())
        colors = ['#7f8c8d', '#27ae60', '#e74c3c']
        
        bars = ax.bar(scenarios, values, color=colors, alpha=0.8, edgecolor='black')
        ax.set_title('Latence P95 par Scénario', fontweight='bold', fontsize=12)
        ax.set_ylabel('Latence (ms)', fontweight='bold')
        ax.grid(axis='y', linestyle='--', alpha=0.7)
        
        # Annotations
        for bar, val in zip(bars, values):
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height,
                   f'{val}ms', ha='center', va='bottom', fontweight='bold')
        
        # Indication du meilleur
        best_idx = values.index(min(values))
        bars[best_idx].set_edgecolor('gold')
        bars[best_idx].set_linewidth(3)
    
    @staticmethod
    def _plot_variance(ax, variance_data):
        """Graphique de variance."""
        scenarios = list(variance_data.keys())
        values = [variance_data[s] for s in scenarios]
        colors = ['#7f8c8d', '#27ae60', '#e74c3c']
        
        bars = ax.bar(scenarios, values, color=colors, alpha=0.8, edgecolor='black')
        ax.set_title('Variance CPU (Équilibrage)', fontweight='bold', fontsize=12)
        ax.set_ylabel('Écart-Type (%)', fontweight='bold')
        ax.grid(axis='y', linestyle='--', alpha=0.7)
        
        for bar, val in zip(bars, values):
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height,
                   f'{val:.2f}%', ha='center', va='bottom', fontweight='bold')
    
    @staticmethod
    def _plot_temporal_cpu(ax, results):
        """Graphique temporel de l'utilisation CPU."""
        for scenario, data in results.items():
            if 'cpu' in data and not data['cpu'].empty:
                df = data['cpu']
                mean_cpu = df.mean(axis=1)
                ax.plot(df.index, mean_cpu, label=scenario, linewidth=2, marker='o', 
                       markersize=3, alpha=0.8)
        
        ax.set_title('Évolution Temporelle de l\'Utilisation CPU Moyenne', 
                    fontweight='bold', fontsize=12)
        ax.set_xlabel('Temps', fontweight='bold')
        ax.set_ylabel('CPU Moyen (%)', fontweight='bold')
        ax.legend(loc='best', framealpha=0.9)
        ax.grid(True, alpha=0.3)
    
    @staticmethod
    def _plot_multimetric_comparison(ax, results):
        """Comparaison des statistiques moyennes."""
        scenarios = list(results.keys())
        mean_values = []
        
        for scenario in scenarios:
            if 'stats' in results[scenario] and results[scenario]['stats']:
                mean_values.append(results[scenario]['stats'].get('mean_usage', 0))
            else:
                mean_values.append(0)
        
        colors = ['#7f8c8d', '#27ae60', '#e74c3c']
        bars = ax.bar(scenarios, mean_values, color=colors, alpha=0.8, edgecolor='black')
        ax.set_title('Utilisation CPU Moyenne', fontweight='bold', fontsize=12)
        ax.set_ylabel('CPU Moyen (%)', fontweight='bold')
        ax.grid(axis='y', linestyle='--', alpha=0.7)
        
        for bar, val in zip(bars, mean_values):
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height,
                   f'{val:.1f}%', ha='center', va='bottom', fontweight='bold')
    
    @staticmethod
    def _plot_imbalance_score(ax, results):
        """Score de déséquilibre."""
        scenarios = list(results.keys())
        scores = []
        
        for scenario in scenarios:
            if 'stats' in results[scenario] and results[scenario]['stats']:
                scores.append(results[scenario]['stats'].get('imbalance', 0))
            else:
                scores.append(0)
        
        colors = ['#7f8c8d', '#27ae60', '#e74c3c']
        bars = ax.bar(scenarios, scores, color=colors, alpha=0.8, edgecolor='black')
        ax.set_title('Score de Déséquilibre (Plus bas = Meilleur)', 
                    fontweight='bold', fontsize=12)
        ax.set_ylabel('Différence Max-Min (%)', fontweight='bold')
        ax.grid(axis='y', linestyle='--', alpha=0.7)
        
        for bar, val in zip(bars, scores):
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height,
                   f'{val:.2f}', ha='center', va='bottom', fontweight='bold')


def print_summary_table(results: Dict):
    """Affiche un tableau récapitulatif des résultats."""
    print("\n" + "="*80)
    print("  TABLEAU RÉCAPITULATIF DES MÉTRIQUES")
    print("="*80)
    print(f"{'Scénario':<25} {'Latence':<12} {'Variance':<12} {'Déséquilibre':<15} {'CPU Moy':<10}")
    print("-"*80)
    
    for scenario in results.keys():
        stats = results[scenario].get('stats', {})
        latency = LATENCY_P95_MS.get(scenario, 0)
        variance = stats.get('variance', 0)
        imbalance = stats.get('imbalance', 0)
        mean_cpu = stats.get('mean_usage', 0)
        
        print(f"{scenario:<25} {latency:<12}ms {variance:<12.2f}% {imbalance:<15.2f}% {mean_cpu:<10.1f}%")
    
    print("="*80 + "\n")


def main():
    """Fonction principale."""
    logger.info("Démarrage de l'analyse Prometheus...")
    
    # Initialisation
    analyzer = PrometheusAnalyzer(PROMETHEUS_URL)
    lb_analyzer = LoadBalanceAnalyzer()
    
    # Collecte des données
    results = {}
    variance_results = {}
    
    for scenario, (start, end) in TIME_RANGES.items():
        logger.info(f"Analyse du scénario: {scenario}")
        
        # Extraction CPU
        df_cpu = analyzer.query_range(METRICS['cpu'], start, end)
        
        # Calcul des statistiques
        stats = lb_analyzer.get_statistics(df_cpu)
        variance_results[scenario] = stats.get('variance', np.nan)
        
        results[scenario] = {
            'cpu': df_cpu,
            'stats': stats
        }
        
        logger.info(f"  → Variance: {stats.get('variance', 0):.2f}%")
    
    # Affichage du tableau récapitulatif
    print_summary_table(results)
    
    # Génération des visualisations
    if not all(pd.isna(list(variance_results.values()))):
        logger.info("Génération des graphiques...")
        Visualizer.plot_comprehensive_analysis(results, variance_results, LATENCY_P95_MS)
        logger.info("✓ Analyse terminée avec succès!")
    else:
        logger.error("✗ Impossible de générer les graphiques: données manquantes")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\nAnalyse interrompue par l'utilisateur")
    except Exception as e:
        logger.error(f"Erreur critique: {e}", exc_info=True)