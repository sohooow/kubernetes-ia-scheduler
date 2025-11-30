#!/usr/bin/env python3
"""
generate_academic_plots.py

Génère les graphiques académiques pour le rapport de recherche.
Focus : Comparaison Latence Baseline vs EL avec affichage du gain.
"""

import json
import matplotlib.pyplot as plt
import numpy as np
import re
from pathlib import Path

# Définition du chemin du répertoire de sortie
RESULTS_FOLDER = "TESTS/RESULTS"

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
    """Charge les résultats des tests depuis la racine du projet."""
    filepath = Path(filename)
    if not filepath.exists():
        filepath = Path('TESTS') / filename
        if not filepath.exists(): return None

    try:
        with open(filepath, 'r') as f:
            content = f.read()
        # Correction du format .50 -> 0.50
        fixed_content = re.sub(r':\s*\.(\d+)', r': 0.\1', content)
        return json.loads(fixed_content)
    except: return None

def plot_latency_p95(data, output=f'{RESULTS_FOLDER}/latency_p95.png'):
    """Graphique Latence avec annotation du gain"""
    scenarios = data['scenarios']
    policies = ['Baseline', 'EL (Latency)']
    latencies = [
        float(scenarios['baseline']['latency_p95_ms']),
        float(scenarios['el_latency']['latency_p95_ms'])
    ]
    colors = ['#95a5a6', '#2ecc71'] # Gris (Baseline) et Vert (Succès)
    
    fig, ax = plt.subplots(figsize=(8, 6))
    bars = ax.bar(policies, latencies, color=colors, edgecolor='black', alpha=0.85)
    
    # Affichage des valeurs sur les barres
    for bar, lat in zip(bars, latencies):
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height,
                f'{lat:.1f} ms', ha='center', va='bottom', fontweight='bold', fontsize=12)
    
    # 🌟 CALCUL ET AFFICHAGE DU GAIN
    try:
        baseline_val = latencies[0]
        el_val = latencies[1]
        if baseline_val > 0:
            gain_pct = (baseline_val - el_val) / baseline_val * 100
            
            if gain_pct > 0:
                # Flèche et texte vert
                ax.annotate(f'-{gain_pct:.1f}% de Latence',
                            xy=(1, el_val), 
                            xytext=(1, el_val + (baseline_val * 0.2)),
                            ha='center', 
                            color='green', 
                            fontweight='bold', 
                            fontsize=12,
                            arrowprops=dict(arrowstyle='->', color='green', lw=2),
                            bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="green", alpha=0.9))
    except Exception as e:
        print(f"Info: Pas d'annotation de gain ({e})")

    ax.set_ylabel('Latence P95 (ms)', fontweight='bold')
    ax.set_title('Impact du Scheduler RL sur la Latence 5G', fontweight='bold', pad=15)
    
    # Ajuster l'échelle Y pour laisser de la place à l'annotation
    ax.set_ylim(0, max(latencies) * 1.35)
    ax.grid(axis='y', alpha=0.3, linestyle='--')
    
    plt.tight_layout()
    plt.savefig(output, dpi=300)
    print(f"✅ Graphique sauvegardé: {output}")
    plt.close()

def plot_pod_distribution(data, output=f'{RESULTS_FOLDER}/pod_distribution.png'):
    """Graphique Distribution des pods"""
    scenarios = data['scenarios']
    policies = ['Baseline', 'EL (Latency)']
    
    worker1 = [scenarios['baseline']['worker1'], scenarios['el_latency']['worker1']]
    worker2 = [scenarios['baseline']['worker2'], scenarios['el_latency']['worker2']]
    
    x = np.arange(len(policies))
    width = 0.35
    
    fig, ax = plt.subplots(figsize=(8, 6))
    bars1 = ax.bar(x - width/2, worker1, width, label='Worker-1 (Low-Latency)', 
                   color='#e74c3c', edgecolor='black', alpha=0.85)
    bars2 = ax.bar(x + width/2, worker2, width, label='Worker-2 (Standard)', 
                   color='#3498db', edgecolor='black', alpha=0.85)
    
    # Valeurs
    for bars in [bars1, bars2]:
        for bar in bars:
            height = bar.get_height()
            if height > 0:
                ax.text(bar.get_x() + bar.get_width()/2., height,
                        f'{int(height)}', ha='center', va='bottom', fontsize=10)
    
    ax.set_ylabel('Nombre de Pods', fontweight='bold')
    ax.set_title('Distribution des Pods par Nœud', fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(policies)
    ax.legend(loc='upper right')
    ax.set_ylim(0, 12)
    ax.grid(axis='y', alpha=0.3, linestyle='--')
    
    plt.tight_layout()
    plt.savefig(output, dpi=300)
    print(f"✅ Graphique sauvegardé: {output}")
    plt.close()

def main():
    print("📊 Génération des graphiques (Latence & Distribution)...")
    data = load_results()
    
    if data:
        Path(RESULTS_FOLDER).mkdir(parents=True, exist_ok=True)
        plot_latency_p95(data)
        plot_pod_distribution(data)
        print("\n✅ Terminé. Graphiques disponibles dans TESTS/RESULTS/")
    else:
        print("❌ Erreur: Impossible de charger academic_results.json")

if __name__ == '__main__':
    main()