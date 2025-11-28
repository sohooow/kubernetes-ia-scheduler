@ -5,6 +5,22 @@ echo "================================================="
echo "🧹 DÉMARRAGE DU NETTOYAGE RADICAL DU SYSTÈME"
echo "================================================="

# --- FONCTION POUR LIRE LA RÉPONSE OUI/NON ---
# Lit la réponse de l'utilisateur (o/n)
confirm_action() {
    # $1 est le message de la question
    read -r -p "$1 (o/n) : " response
    case "$response" in
        [oO][uI]|[oO])
            true
            ;;
        *)
            false
            ;;
    esac
}
# ---------------------------------------------

# 1. SUPPRESSION DES CLUSTERS K3D
echo -e "\n--- Suppression de tous les clusters K3d..."
k3d cluster delete --all || true
@ -27,4 +43,13 @@ rm -rf .venv
rm -rf __pycache__
rm -rf schedulers/__pycache__

# --- CONDITION IF POUR LE MODÈLE ---
if confirm_action "Souhaitez-vous aussi supprimer le fichier modèle 'rl_scheduler_model.pth' ?"; then
    echo "    -> Suppression du modèle 'rl_scheduler_model.pth'..."
    rm -rf rl_scheduler_model.pth
else
    echo "    -> Le fichier modèle 'rl_scheduler_model.pth' est conservé."
fi
# ------------------------------------

echo -e "\n✅ Nettoyage terminé. Le système est prêt à être recréé."