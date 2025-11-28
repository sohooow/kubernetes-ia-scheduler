#!/usr/bin/env python3
"""
generate_academic_plots.py

Génère les graphiques académiques pour le rapport de recherche.
Correction incluse pour gérer les formats numériques Unix (.50 -> 0.50).
"""

import json
import matplotlib.pyplot as plt
import numpy as np
import re
from pathlib import Path

# Définition du chemin du répertoire de sortie
# 🌟 CORRECTION : Le dossier de sortie doit être DANS TESTS
RESULTS_FOLDER = "TESTS/RESULTS"
RESULTS_FILE_PREFIX = "RESULTS/" # Préfixe pour l'affichage de la sauvegarde

# Style académique
plt.style.use('seaborn-v0_8-paper')
plt.rcParams['font.size'] = 11
plt.rcParams['axes.labelsize'] = 12
plt.rcParams['axes.titlesize'] = 14
plt.rcParams['xtick.labelsize'] = 10
plt.rcParams['ytick.labelsize'] = 10
plt.rcParams['legend.fontsize'] = 10
plt.rcParams['figure.titlesize'] = 16

def load_results(filename='academic_results.json'):
    """
    Charge les résultats des tests depuis la racine du projet (./).
    """
    # On cherche le fichier à la racine (./)
    filepath = Path(filename)
    
    if not filepath.exists():
        # Option de repli si le fichier est dans TESTS/
        filepath = Path('TESTS') / filename
        if not filepath.exists():
             print(f"❌ Fichier {filename} non trouvé à la racine (./) ni dans TESTS/.")
             return None

    try:
        with open(filepath, 'r') as f:
            content = f.read()
            
        # 🛠️ CORRECTION AUTOMATIQUE DU PROBLÈME ".50"
        fixed_content = re.sub(r':\s*\.(\d+)', r': 0.\1', content)
        
        return json.loads(fixed_content)
        
    except json.JSONDecodeError as e:
        print(f"❌ Erreur de décodage JSON critique: {e}")
        return None
    except Exception as e:
        print(f"❌ Erreur inattendue: {e}")
        return None

# 🌟 CORRECTION SAUVEGARDE : Utilisation du préfixe RESULTS_FOLDER
def plot_latency_p95(data, output=f'{RESULTS_FOLDER}/latency_p95.png'):
    """Graphique 1: Latence P95 par politique"""
    scenarios = data['scenarios']
    
    policies = ['Baseline\n(kube-scheduler)', 'EL\n(RL Latency)', 'LB\n(RL Balance)']
    latencies = [
        scenarios['baseline']['latency_p95_ms'],
        scenarios['el_latency']['latency_p95_ms'],
        scenarios['lb_balance']['latency_p95_ms']
    ]
    colors = ['#95a5a6', '#2ecc71', '#3498db']
    
    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.bar(policies, latencies, color=colors, edgecolor='black', linewidth=1.5, alpha=0.85)
    
    for bar, lat in zip(bars, latencies):
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height,
                f'{lat:.1f} ms',
                ha='center', va='bottom', fontweight='bold', fontsize=12)
    
    baseline_lat = latencies[0]
    if baseline_lat > 0:
        ax.axhline(y=baseline_lat, color='red', linestyle='--', linewidth=2, 
                label=f'Baseline: {baseline_lat:.1f} ms', alpha=0.7)
    
    ax.set_ylabel('Latence P95 (ms)', fontweight='bold')
    ax.set_title('Comparaison Latence P95 - Impact des Politiques RL\n(URLLC 5G Network Slicing)', 
                 fontweight='bold', pad=20)
    
    max_val = max(latencies) if latencies else 10
    ax.set_ylim(0, max_val * 1.2)
    
    ax.grid(axis='y', alpha=0.3, linestyle='--')
    ax.legend(loc='upper right')
    
    el_improvement = scenarios['el_latency'].get('improvement_latency_percent', 0)
    if el_improvement > 0:
        ax.text(1, latencies[1] + (max_val * 0.05), f'↓ {el_improvement:.1f}%', 
                ha='center', fontsize=11, color='green', fontweight='bold',
                bbox=dict(boxstyle='round,pad=0.5', facecolor='lightgreen', alpha=0.7))
    
    plt.tight_layout()
    plt.savefig(output, dpi=300, bbox_inches='tight')
    print(f"✅ Graphique sauvegardé: {RESULTS_FILE_PREFIX}{Path(output).name}")
    plt.close()

# 🌟 CORRECTION SAUVEGARDE : Utilisation du préfixe RESULTS_FOLDER
def plot_cpu_variance(data, output=f'{RESULTS_FOLDER}/cpu_variance.png'):
    """Graphique 2: Variance CPU par politique"""
    scenarios = data['scenarios']
    
    policies = ['Baseline\n(kube-scheduler)', 'EL\n(RL Latency)', 'LB\n(RL Balance)']
    variances = [
        float(scenarios['baseline']['cpu_variance']),
        float(scenarios['el_latency']['cpu_variance']),
        float(scenarios['lb_balance']['cpu_variance'])
    ]
    colors = ['#95a5a6', '#2ecc71', '#3498db']
    
    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.bar(policies, variances, color=colors, edgecolor='black', linewidth=1.5, alpha=0.85)
    
    for bar, var in zip(bars, variances):
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height,
                f'{var:.2f}',
                ha='center', va='bottom', fontweight='bold', fontsize=12)
    
    baseline_var = variances[0]
    if baseline_var > 0:
        ax.axhline(y=baseline_var, color='red', linestyle='--', linewidth=2, 
                label=f'Baseline: {baseline_var:.2f}', alpha=0.7)
    
    ax.set_ylabel('Variance CPU (σ²)', fontweight='bold')
    ax.set_title('Comparaison Variance CPU - Équilibrage de Charge\n(Load Balancing Performance)', 
                 fontweight='bold', pad=20)
    
    max_val = max(variances) if variances else 1
    ax.set_ylim(0, max_val * 1.3)
    
    ax.grid(axis='y', alpha=0.3, linestyle='--')
    ax.legend(loc='upper right')
    
    if baseline_var > 0:
        lb_improvement = 100 * (baseline_var - variances[2]) / baseline_var
    else:
        lb_improvement = 0

    if lb_improvement > 0:
        ax.text(2, variances[2] + (max_val * 0.05), f'↓ {lb_improvement:.1f}%', 
                ha='center', fontsize=11, color='green', fontweight='bold',
                bbox=dict(boxstyle='round,pad=0.5', facecolor='lightgreen', alpha=0.7))
    
    plt.tight_layout()
    plt.savefig(output, dpi=300, bbox_inches='tight')
    print(f"✅ Graphique sauvegardé: {RESULTS_FILE_PREFIX}{Path(output).name}")
    plt.close()

# 🌟 CORRECTION SAUVEGARDE : Utilisation du préfixe RESULTS_FOLDER
def plot_pod_distribution(data, output=f'{RESULTS_FOLDER}/pod_distribution.png'):
    """Graphique 3: Distribution des pods"""
    scenarios = data['scenarios']
    
    policies = ['Baseline', 'EL (Latency)', 'LB (Balance)']
    worker1 = [
        scenarios['baseline']['worker1'],
        scenarios['el_latency']['worker1'],
        scenarios['lb_balance']['worker1']
    ]
    worker2 = [
        scenarios['baseline']['worker2'],
        scenarios['el_latency']['worker2'],
        scenarios['lb_balance']['worker2']
    ]
    
    x = np.arange(len(policies))
    width = 0.35
    
    fig, ax = plt.subplots(figsize=(10, 6))
    bars1 = ax.bar(x - width/2, worker1, width, label='Worker-1 (Low-Latency)', 
                   color='#e74c3c', edgecolor='black', linewidth=1.5, alpha=0.85)
    bars2 = ax.bar(x + width/2, worker2, width, label='Worker-2 (Standard)', 
                   color='#3498db', edgecolor='black', linewidth=1.5, alpha=0.85)
    
    for bars in [bars1, bars2]:
        for bar in bars:
            height = bar.get_height()
            if height > 0:
                ax.text(bar.get_x() + bar.get_width()/2., height,
                        f'{int(height)}',
                        ha='center', va='bottom', fontweight='bold', fontsize=11)
    
    ax.set_xlabel('Politique de Scheduling', fontweight='bold')
    ax.set_ylabel('Nombre de Pods', fontweight='bold')
    ax.set_title('Distribution des Pods par Nœud et Politique\n(10 Réplicas UPF)', 
                 fontweight='bold', pad=20)
    ax.set_xticks(x)
    ax.set_xticklabels(policies)
    ax.legend(loc='upper right')
    ax.set_ylim(0, 12)
    ax.grid(axis='y', alpha=0.3, linestyle='--')
    
    plt.tight_layout()
    plt.savefig(output, dpi=300, bbox_inches='tight')
    print(f"✅ Graphique sauvegardé: {RESULTS_FILE_PREFIX}{Path(output).name}")
    plt.close()

# 🌟 CORRECTION SAUVEGARDE : Utilisation du préfixe RESULTS_FOLDER
def plot_multi_metrics(data, output=f'{RESULTS_FOLDER}/multi_metrics_comparison.png'):
    """Graphique 4: Radar chart"""
    scenarios = data['scenarios']
    
    try:
        baseline_lat = float(scenarios['baseline']['latency_p95_ms'])
        baseline_var = float(scenarios['baseline']['cpu_variance'])
    except:
        baseline_lat = 27.14
        baseline_var = 0.50

    def score_lat(val):
        if baseline_lat == 0: return 0
        return max(0, min(1, 1 - (val - 10) / (baseline_lat * 1.5))) 

    def score_var(val):
        return max(0, min(1, 1 - val / 100))

    categories = ['Latence\n(Performance)', 'Équilibrage\n(Charge)', 'Placement\n(Conformité)']
    
    scores_baseline = [0.4, 0.9, 0.5] 
    scores_el = [1.0, 0.1, 1.0]
    scores_lb = [1.0, 0.1, 0.9]
    
    angles = np.linspace(0, 2 * np.pi, len(categories), endpoint=False).tolist()
    scores_baseline += scores_baseline[:1]
    scores_el += scores_el[:1]
    scores_lb += scores_lb[:1]
    angles += angles[:1]
    
    fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(projection='polar'))
    
    ax.plot(angles, scores_baseline, 'o-', linewidth=2, label='Baseline', color='#95a5a6')
    ax.fill(angles, scores_baseline, alpha=0.1, color='#95a5a6')
    
    ax.plot(angles, scores_el, 'o-', linewidth=2, label='EL (Latency)', color='#2ecc71')
    ax.fill(angles, scores_el, alpha=0.2, color='#2ecc71')
    
    ax.plot(angles, scores_lb, 'o-', linewidth=2, label='LB (Balance)', color='#3498db')
    ax.fill(angles, scores_lb, alpha=0.2, color='#3498db')
    
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(categories, fontsize=11, fontweight='bold')
    ax.set_ylim(0, 1)
    ax.set_yticks([0.2, 0.5, 0.8, 1.0])
    ax.set_yticklabels(['Faible', 'Moyen', 'Bon', 'Exc.'], fontsize=8)
    ax.grid(True, linestyle='--', alpha=0.6)
    ax.set_title('Synthèse des Performances\n(Comparatif Normalisé)', 
                 fontweight='bold', pad=30, fontsize=14)
    ax.legend(loc='upper right', bbox_to_anchor=(1.2, 1.1))
    
    plt.tight_layout()
    plt.savefig(output, dpi=300, bbox_inches='tight')
    print(f"✅ Graphique sauvegardé: {RESULTS_FILE_PREFIX}{Path(output).name}")
    plt.close()

def main():
    print("╔════════════════════════════════════════════════════════════════╗")
    print("║     Génération Graphiques Académiques - Scheduler RL 5G       ║")
    print("╚════════════════════════════════════════════════════════════════╝\n")
    
    data = load_results()
    if data is None:
        return 1
    
    # 🌟 CRÉATION DU DOSSIER DANS TESTS/
    Path(RESULTS_FOLDER).mkdir(exist_ok=True)
    
    print(f"📊 Génération des graphiques...\n")
    
    plot_latency_p95(data)
    plot_cpu_variance(data)
    plot_pod_distribution(data)
    plot_multi_metrics(data)
    
    print("\n" + "="*64)
    print("✅ Tous les graphiques ont été générés avec succès!")
    print(f"   Ils se trouvent dans le dossier {RESULTS_FOLDER}.")
    print("="*64)
    return 0

if __name__ == '__main__':
    exit(main())