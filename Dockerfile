# Utilise une image Python légère comme base
FROM python:3.11-slim

# Définir le répertoire de travail dans le conteneur
WORKDIR /app

# Copier le fichier des dépendances et les installer
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copier le code du scheduler
COPY ia_scheduler.py .
COPY scoring_logic.py .

# Définir la commande pour exécuter le scheduler
# L'utilisation de 'python -u' assure que les logs sont affichés immédiatement (unbuffered)
CMD ["python", "-u", "ia_scheduler.py"]