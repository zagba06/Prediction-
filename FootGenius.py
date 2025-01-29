
import os
import random
import html
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import threading
import types
import json
import sqlite3
import math
import time
import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton
import numpy as np 

from flask import Flask, request
import telebot

app = Flask(__name__)

@app.route('/')
def home():
    return 'Bot is running!'

@app.route('/webhook', methods=['POST'])
def webhook():
    json_str = request.get_data().decode('UTF-8')
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return '', 200

bot.remove_webhook()  # Supprime l'ancien webhook, si un existe
bot.set_webhook(url="https://ton_domaine.com/webhook")  # Définit le nouveau webhook

if __name__ == "__main__":
    # Flask sera géré par Gunicorn en production, donc cette ligne est inutile
    pass

# Initialisation du bot avec le token

# Récupérer le TOKEN de la variable d'environnement
TOKEN = os.getenv("TOKEN_BOT")

# Créer le bot avec le TOKEN
bot = telebot.TeleBot(TOKEN)

# Définir les données de la montante globalement
montante_data = {
    "active": False,
    "initial_bet": 0.0,
    "multiplier": 2.0,
    "current_level": 0,
    "max_levels": 5,
    "current_bet": 0.0,
    "history": []
}

# Fonction pour créer la base de données
def create_db():
    conn = sqlite3.connect('bankroll.db')  # Nom de la base de données
    c = conn.cursor()

    # Créer une table pour la bankroll (avec la colonne bets)
    c.execute('''CREATE TABLE IF NOT EXISTS bankroll (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    initial_balance REAL NOT NULL,
                    balance REAL NOT NULL,
                    bets TEXT, 
                    date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )''') 

    # Créer une table pour les paris
    c.execute('''CREATE TABLE IF NOT EXISTS bets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stake REAL,
                    odds REAL,
                    result TEXT,
                    profit REAL,
                    bet_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )''')

    # Table pour les paris en attente
    c.execute('''CREATE TABLE IF NOT EXISTS pending_bets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stake REAL,
                    odds REAL,
                    status TEXT
                )''')

    # Créer une table pour les retraits
    c.execute('''CREATE TABLE IF NOT EXISTS withdrawals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    amount REAL,
                    date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )''')

    # Créer la table pour la montante
    c.execute('''CREATE TABLE IF NOT EXISTS montante (
                    id INTEGER PRIMARY KEY, 
                    initial_bet REAL, 
                    multiplier REAL, 
                    max_levels INTEGER, 
                    current_level INTEGER, 
                    current_bet REAL, 
                    history TEXT, 
                    active INTEGER
                )''')

    # Convertir l'historique des mises en chaîne de caractères
    history_str = ",".join(map(str, montante_data["history"]))

    # Enregistrer les données dans la base de données (en remplaçant l'entrée avec id=1)
    c.execute('''INSERT OR REPLACE INTO montante (id, initial_bet, multiplier, max_levels, current_level, 
                      current_bet, history, active) 
                      VALUES (1, ?, ?, ?, ?, ?, ?, ?)''',
               (montante_data["initial_bet"], montante_data["multiplier"], montante_data["max_levels"],
                montante_data["current_level"], montante_data["current_bet"], history_str, 
                int(montante_data["active"])))

    conn.commit()  # Valider les changements dans la base
    conn.close()  # Fermer la connexion

# Appel de la fonction pour créer la base de données
create_db()

# Définition des variables globales
bankroll = {
    "initial_balance": 0.0,  # Bankroll initiale
    "balance": 0.0,  # Solde actuel
    "bets": [],  # Liste des paris
    "withdrawals": [],  # Liste des retraits
    "pending_bets": []  # Liste des paris en attente
}

# Gestion des étapes
current_step = {
    "team": None,  # 'domicile' ou 'exterieur'
    "data_type": None  # 'globaux', 'terrain', 'cartons', 'corners'
}

data_steps = ["globaux", "terrain", "cartons", "corners"]


#Donnés de sauvegarde 
def save_bankroll():
    """Sauvegarde la bankroll dans la base de données"""
    conn = sqlite3.connect('bankroll.db')
    cursor = conn.cursor()
    
    # Sauvegarder la bankroll (balance et initial_balance) avec la liste des paris
    cursor.execute('''
    INSERT INTO bankroll (initial_balance, balance, bets) VALUES (?, ?, ?)
    ''', (bankroll["initial_balance"], bankroll["balance"], json.dumps(bankroll["bets"])))  # Utiliser JSON pour éviter eval
    conn.commit()
    conn.close()


def load_bankroll():
    """Charge la bankroll depuis la base de données."""
    conn = sqlite3.connect('bankroll.db')
    cursor = conn.cursor()

    # Charger les données de la bankroll (initial_balance, balance, bets)
    cursor.execute('SELECT initial_balance, balance, bets FROM bankroll ORDER BY id DESC LIMIT 1')
    result = cursor.fetchone()

    if result:
        bankroll["initial_balance"] = result[0]
        bankroll["balance"] = result[1]
        bankroll["bets"] = json.loads(result[2]) if result[2] else []  # Utiliser json.loads pour les paris

        # Charger les retraits via la fonction load_withdrawals
        load_withdrawals()  # Charge directement les retraits

        conn.close()
        return True

    conn.close()
    return False

def save_pending_bets():
    """Sauvegarde les paris en attente dans la base de données."""
    conn = sqlite3.connect('bankroll.db')
    cursor = conn.cursor()

    # Efface les anciennes entrées pour éviter les doublons
    cursor.execute("DELETE FROM pending_bets")

    # Insère chaque pari en attente dans la base de données
    for bet in pending_bets:
        cursor.execute('''
        INSERT INTO pending_bets (stake, odds, status)
        VALUES (?, ?, ?)
        ''', (bet["stake"], bet["odds"], bet["status"]))

    conn.commit()
    conn.close()

def load_pending_bets():
    """Charge les paris en attente depuis la base de données."""
    global pending_bets  # Déclarer pending_bets comme une variable globale
    conn = sqlite3.connect('bankroll.db')
    cursor = conn.cursor()

    cursor.execute("SELECT stake, odds, status FROM pending_bets")
    rows = cursor.fetchall()

    # Remplit la liste des paris en attente
    pending_bets = [{"stake": row[0], "odds": row[1], "status": row[2]} for row in rows]

    conn.close()

def save_withdrawal(amount):
    """Enregistre un retrait dans la base de données."""
    conn = sqlite3.connect('bankroll.db')
    cursor = conn.cursor()
    cursor.execute('''
    INSERT INTO withdrawals (amount) VALUES (?)
    ''', (amount,))
    conn.commit()
    conn.close()

def load_withdrawals():
    """Charge les retraits depuis la base de données."""
    conn = sqlite3.connect('bankroll.db')
    cursor = conn.cursor()
    cursor.execute('SELECT amount, date FROM withdrawals')
    withdrawals = cursor.fetchall()
    conn.close()
    
    # Charger les retraits dans la structure globale
    for withdrawal in withdrawals:
        bankroll["withdrawals"].append({
            "amount": withdrawal[0],
            "date": withdrawal[1]
        })


#Save montante
def save_montante_data():
    """Sauvegarder les données de la montante dans la base de données."""
    conn = sqlite3.connect('montante.db')  # Remplacez par le chemin correct vers votre base de données
    cursor = conn.cursor()
    
    # Récupérer les données de montante_data
    initial_bet = montante_data["initial_bet"]
    multiplier = montante_data["multiplier"]
    max_levels = montante_data["max_levels"]
    current_level = montante_data["current_level"]
    current_bet = montante_data["current_bet"]
    history = ",".join(map(str, montante_data["history"]))  # Convertir la liste en chaîne de caractères
    active = montante_data["active"]
    
    # Insérer ou mettre à jour les données dans la table 'montante'
    cursor.execute('''
        INSERT OR REPLACE INTO montante (id, initial_bet, multiplier, max_levels, current_level, current_bet, history, active)
        VALUES (1, ?, ?, ?, ?, ?, ?, ?)
    ''', (initial_bet, multiplier, max_levels, current_level, current_bet, history, active))

    conn.commit()
    conn.close()

# Fonction pour charger les données de la montante
def load_montante_data():
    """Charger les données de la montante depuis la base de données SQLite."""
    conn = sqlite3.connect("montante.db")
    cursor = conn.cursor()

    # Récupérer les données de la montante (id=1)
    cursor.execute('SELECT * FROM montante WHERE id = 1')
    row = cursor.fetchone()

    if row:
        # Récupérer et assigner les données
        montante_data["initial_bet"], montante_data["multiplier"], montante_data["max_levels"], \
        montante_data["current_level"], montante_data["current_bet"], history_str, active = row[1:]

        # Vérifier si l'historique est vide
        if history_str:
            # Si l'historique n'est pas vide, convertir la chaîne en une liste de flottants
            montante_data["history"] = list(map(float, history_str.split(",")))
        else:
            # Si l'historique est vide, initialiser avec une liste vide
            montante_data["history"] = []

        # Restaurer l'état actif ou non de la montante
        montante_data["active"] = bool(active)

        conn.close()  # Fermer la connexion
        return montante_data
    else:
        conn.close()  # Fermer la connexion
        return None

def rest_bankroll():
    """Réinitialise entièrement la bankroll."""
    global bankroll  # Utilisation de la variable globale `bankroll`

    # Réinitialiser les données en mémoire
    bankroll["balance"] = 0
    bankroll["bets"] = []
    bankroll["withdrawals"] = []
    bankroll["pending_bets"] = []

    # Connexion à la base de données
    conn = sqlite3.connect('bankroll.db')
    cursor = conn.cursor()

    try:
        # Réinitialiser les tables dans la base de données
        cursor.execute("DELETE FROM bets")  # Supprime les paris
        cursor.execute("DELETE FROM withdrawals")  # Supprime les retraits
        cursor.execute("DELETE FROM pending_bets")  # Supprime les paris en attente

        # Si nécessaire, remettre un solde initial par défaut
        cursor.execute("UPDATE bankroll SET balance = 0 WHERE id = 1")

        conn.commit()
        print("La bankroll a été réinitialisée dans la base de données.")
    except sqlite3.Error as e:
        print(f"Erreur lors de la réinitialisation de la bankroll : {e}")
    finally:
        conn.close()
        

# Sauvegarder la bankroll
@bot.message_handler(func=lambda msg: msg.text == "💾 Sauvegarder Bankroll")
def save_bankroll_action(message):
    """Sauvegarde la bankroll dans la base de données."""
    save_bankroll()
    bot.send_message(message.chat.id, "💾 Bankroll sauvegardée avec succès ✅ !")

# Charger la bankroll
@bot.message_handler(func=lambda msg: msg.text == "📂 Charger Bankroll")
def load_bankroll_action(message):
    """Charge la bankroll depuis la base de données."""
    if load_bankroll():
        bot.send_message(message.chat.id, f"📂 Bankroll chargée avec succès ✅ !\n💰 Solde actuel : {bankroll['balance']:.2f} F CFA")
    else:
        bot.send_message(message.chat.id, "⚠️ Aucune bankroll sauvegardée trouvée.")
        
# Fonctions pour créer les menus
def create_start_menu():
    """Menu de démarrage"""
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton("🤑 Start 🤑"))
    return markup

# Menu principal
def create_main_menu():
    """Menu principal du bot."""
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton("💻 Analyse de Match 💻"))
    markup.add(KeyboardButton("🔍 Value Bet 🔍"))  # Nouveau bouton pour les value bets
    markup.add(KeyboardButton("💵 Bankroll 💵"))
    markup.add(KeyboardButton("💹 Montante"))  # Nouveau bouton pour la montante
    markup.add(KeyboardButton("❌ Quitter ❌"))
    return markup

# Calcul des Value Bets
def calculate_value_bet(probability_percent, bookmaker_odd):
    """
    Calcule si un pari est un value bet.

    Args:
        probability_percent (float): Probabilité estimée en pourcentage (exemple : 65 pour 65%).
        bookmaker_odd (float): Cote proposée par le bookmaker.

    Returns:
        bool, float: True si c'est un value bet, sinon False. Retourne aussi la valeur.
    """
    probability = probability_percent / 100  # Conversion en probabilité décimale
    value = (probability * bookmaker_odd) - 1
    return value > 0, round(value, 3)

# Gestionnaire pour le bouton Value Bet
@bot.message_handler(func=lambda message: message.text == "🔍 Value Bet 🔍")
def handle_value_bet(message):
    """Gère la recherche de Value Bets."""
    bot.send_message(message.chat.id, "🔢 Entrez la probabilité estimée (en % : exemple 65) :")
    bot.register_next_step_handler(message, process_probability)

# Fonction pour traiter la probabilité estimée
def process_probability(message):
    try:
        probability_percent = float(message.text)
        bot.send_message(message.chat.id, "🔢 Entrez la cote du bookmaker :")
        bot.register_next_step_handler(message, process_odd, probability_percent)
    except ValueError:
        bot.send_message(message.chat.id, "⚠️ Veuillez entrer une probabilité valide (ex : 65).")
        bot.register_next_step_handler(message, process_probability)

# Fonction pour traiter la cote du bookmaker
def process_odd(message, probability_percent):
    try:
        bookmaker_odd = float(message.text)
        is_value_bet, value = calculate_value_bet(probability_percent, bookmaker_odd)
        if is_value_bet:
            bot.send_message(message.chat.id, f"✅ **Value Bet trouvé !**\n"
                                              f"🎯 Valeur : {value}\n"
                                              f"Ce pari est rentable à long terme.")
        else:
            bot.send_message(message.chat.id, "❌ Ce pari n'est pas un Value Bet. Essayez avec d'autres données.")
    except ValueError:
        bot.send_message(message.chat.id, "⚠️ Veuillez entrer une cote valide (ex : 2.5).")
        bot.register_next_step_handler(message, process_odd, probability_percent)
        
# Gestionnaire pour le bouton Retour
@bot.message_handler(func=lambda message: message.text == "↩️ Retour")
def return_to_menu_handler(message):
    """Gère la commande Retour."""
    markup = create_main_menu()
    bot.send_message(message.chat.id, "↩️ Retour au menu principal :", reply_markup=markup)


# Menu Montante
def create_montante_menu():
    """Menu principal pour la montante."""
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton("⚙️ Configurer la Montante"))
    markup.add(KeyboardButton("🚀 Lancer la Montante"))
    markup.add(KeyboardButton("⏹️ Arrêter la Montante"))
    markup.add(KeyboardButton("📜 Historique des Mises"))
    markup.add(KeyboardButton("♻️ Réinitialiser la Montante"))
    markup.add(KeyboardButton("💾 Sauvegarder la Montante"))  # Nouveau bouton pour sauvegarder
    markup.add(KeyboardButton("📂 Charger la Montante"))      # Nouveau bouton pour charger
    markup.add(KeyboardButton("↩️ Retour"))  # Bouton de retour
    return markup

@bot.message_handler(func=lambda msg: msg.text == "💾 Sauvegarder la Montante")
def save_montante(message):
    """Sauvegarder les données de la montante."""
    user_id = message.chat.id  # Utiliser l'ID Telegram comme clé
    if montante_data["active"]:
        save_montante_data()  # Appel correct
        bot.send_message(message.chat.id, "✅ Données de la montante sauvegardées avec succès.")
    else:
        bot.send_message(message.chat.id, "⚠️ Aucune montante active à sauvegarder.")


@bot.message_handler(func=lambda msg: msg.text == "📂 Charger la Montante")
def load_montante(message):
    """Charger les données de la montante."""
    user_id = message.chat.id  # Utiliser l'ID Telegram comme clé
    loaded_data = load_montante_data()  # Charger les données depuis la DB
    
    if loaded_data:  # Si des données ont été chargées
        global montante_data
        montante_data = loaded_data  # Mettre à jour les données globales avec les données chargées
        bot.send_message(message.chat.id, "✅ Données de la montante chargées avec succès.")
    else:
        bot.send_message(message.chat.id, "⚠️ Aucune donnée sauvegardée trouvée.")
        

# Gérer le bouton de la montante
@bot.message_handler(func=lambda msg: msg.text == "💹 Montante")
def montante_menu(message):
    """Afficher le menu de la montante."""
    bot.send_message(
        message.chat.id,
        "Bienvenue dans le module de gestion de montante. Que souhaitez-vous faire ?",
        reply_markup=create_montante_menu()
    )


# Configurer la montante :
@bot.message_handler(func=lambda msg: msg.text == "⚙️ Configurer la Montante")
def configure_montante(message):
    """Configurer les paramètres de la montante."""
    bot.send_message(
        message.chat.id,
        "Entrez les paramètres de la montante sous le format suivant :\n"
        "`mise_initiale cote max_niveaux`\n"
        "Exemple : `10 2 5` (Mise initiale , Cote ,  niveaux)",
        parse_mode="Markdown"
    )

    # Cette fonction sera appelée pour récupérer les paramètres de la montante
    @bot.message_handler(func=lambda msg: True)  # Récupérer les paramètres
    def set_montante_params(msg):
        try:
            params = list(map(float, msg.text.split()))
            if len(params) != 3:
                raise ValueError("Format incorrect")
            # Assurer la validité des paramètres
            initial_bet, multiplier, max_levels = params
            if initial_bet <= 0 or multiplier <= 0 or max_levels <= 0:
                raise ValueError("Les valeurs doivent être supérieures à 0")
            
            montante_data["initial_bet"], montante_data["multiplier"], montante_data["max_levels"] = params
            montante_data["current_level"] = 0
            montante_data["current_bet"] = montante_data["initial_bet"]
            montante_data["history"] = []
            montante_data["active"] = True

            bot.send_message(msg.chat.id, "✅ Montante configurée avec succès.")
            save_montante_data()  # Sauvegarder les données après configuration
        except ValueError as e:
            bot.send_message(msg.chat.id, f"⚠️ Erreur : {str(e)}. Réessayez.")


# Lancer la montante
@bot.message_handler(func=lambda msg: msg.text == "🚀 Lancer la Montante")
def launch_montante(message):
    """Lancer ou continuer la montante."""
    if not montante_data["active"]:
        bot.send_message(message.chat.id, "⚠️ Vous devez d'abord configurer la montante.")
        return

    if montante_data["current_level"] < montante_data["max_levels"]:
        bet = montante_data["current_bet"]
        montante_data["history"].append(bet)
        montante_data["current_level"] += 1
        montante_data["current_bet"] *= montante_data["multiplier"]

        markup = ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add(KeyboardButton("✅ Gagné"), KeyboardButton("❌ Perdu"))

        bot.send_message(
            message.chat.id,
            f"📈 Niveau {montante_data['current_level']}/{montante_data['max_levels']} :\n"
            f"🔶 Mise actuelle : {bet:.2f} F CFA\n"
            f"♻️ Mise suivante : {montante_data['current_bet']:.2f} F CFA\n",
            reply_markup=markup
        )
    else:
        bot.send_message(message.chat.id, "✅ Montante terminée !")
        # Le montant total obtenu est simplement la mise du dernier niveau
        total_winnings = montante_data["current_bet"]

        bot.send_message(
            message.chat.id,
            f"🚀🤑 **Félicitations !** 🤑🚀\n\n"
            f"🎯 Vous avez terminé la montante avec succès ! 🏆\n\n"
            f"💰 **Montant total obtenu** : {total_winnings:.2f} **F CFA**\n\n",
            parse_mode="Markdown",
        )
        reset_montante(message)
        bot.send_message(message.chat.id, "Retour au menu de la Montante.", reply_markup=create_montante_menu())

@bot.message_handler(func=lambda msg: msg.text in ["✅ Gagné", "❌ Perdu"])
def handle_bet_result(message):
    """Gérer le résultat de la mise actuelle."""
    if not montante_data["active"]:
        bot.send_message(message.chat.id, "⚠️ Aucune montante active.")
        return

    if message.text == "✅ Gagné":
        if montante_data["current_level"] == montante_data["max_levels"]:
            # Le montant total obtenu est simplement la mise du dernier niveau
            total_winnings = montante_data["current_bet"]

            bot.send_message(
                message.chat.id,
                f"🚀🤑 **Félicitations !** 🤑🚀\n\n"
                f"🎯 Vous avez terminé la montante avec succès ! 🏆\n\n"
                f"💰 **Montant total obtenu** : {total_winnings:.2f} **F CFA**\n\n",
                parse_mode="Markdown",
            )
            bot.send_message(message.chat.id, "✅ Montante terminée !")
            reset_montante(message)
            bot.send_message(message.chat.id, "Retour au menu de la Montante.", reply_markup=create_montante_menu())
        else:
            bot.send_message(message.chat.id, "🤑 Félicitations ! Vous avez gagné.")
            # Appeler la fonction pour modifier la cote
            ask_for_cote(message)

    elif message.text == "❌ Perdu":
        bot.send_message(message.chat.id, "🥶 Désolé, vous avez perdu. Réinitialisation de la montante.")
        reset_montante(message)
        bot.send_message(message.chat.id, "Retour au menu de la Montante.", reply_markup=create_montante_menu())


def ask_for_cote(message):
    """Demander à l'utilisateur de modifier la cote après un gain."""
    bot.send_message(message.chat.id, "⚡️ Entrez la nouvelle cote (par exemple, 1.2 pour augmenter de 20%) :")
    bot.register_next_step_handler(message, set_new_cote)


def set_new_cote(message):
    """Mettre à jour la cote et revenir au menu principal."""
    try:
        new_cote = float(message.text)
        if new_cote <= 0:
            bot.send_message(message.chat.id, "⚠️ La cote doit être supérieure à 0.")
            ask_for_cote(message)  # Redemander la cote
            return

        montante_data["multiplier"] = new_cote  # Mise à jour de la "cote" dans les données
        bot.send_message(message.chat.id, f"✅ La cote a été mise à jour à {new_cote:.2f}.")
        bot.send_message(message.chat.id, "Retour au menu principal.", reply_markup=create_montante_menu())
    except ValueError:
        bot.send_message(message.chat.id, "⚠️ Vous devez entrer un nombre valide.")
        ask_for_cote(message)  # Redemander la cote        

# Fonction arrêt de montante
@bot.message_handler(func=lambda msg: msg.text == "⏹️ Arrêter la Montante")
def stop_montante(message):
    """Arrêter manuellement la montante."""
    montante_data["active"] = False
    bot.send_message(message.chat.id, "⏹️ Montante arrêtée.")


# Historique de montante 
@bot.message_handler(func=lambda msg: msg.text == "📜 Historique des Mises")
def show_montante_history(message):
    """Afficher l'historique des mises."""
    if not montante_data["history"]:
        bot.send_message(message.chat.id, "⚠️ Aucun historique disponible.")
    else:
        history = "\n".join([f"Niveau {i + 1} : Mise: {bet:.2f} F CFA" for i, bet in enumerate(montante_data["history"])])
        bot.send_message(message.chat.id, f"📜 Historique des mises :\n{history}")


# Réinitialiser la montante :
@bot.message_handler(func=lambda msg: msg.text == "♻️ Réinitialiser la Montante")
def reset_montante(message):
    """Réinitialiser la montante."""
    montante_data["active"] = False
    montante_data["initial_bet"] = 0
    montante_data["multiplier"] = 2
    montante_data["current_level"] = 0
    montante_data["max_levels"] = 5
    montante_data["current_bet"] = 0
    montante_data["history"] = []

    bot.send_message(message.chat.id, "♻️ Montante réinitialisée.")
    
# Retour au menu principal :
@bot.message_handler(func=lambda msg: msg.text == "↩️ Retour")
def back_to_main_menu(message):
    """Retourner au menu principal."""
    bot.send_message(message.chat.id, "Retour au menu principal.", reply_markup=create_main_menu())
    

# Gestion du bouton 💵 Bankroll 💵
@bot.message_handler(func=lambda msg: msg.text == "💵 Bankroll 💵")
def bankroll_menu(message):
    """Affiche le menu pour gérer la bankroll."""
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton("➕ Ajouter un pari"))
    markup.add(KeyboardButton("⏳ Paris en attente"), KeyboardButton("🗄️ Historique de paris"))
    markup.add(KeyboardButton("📊 Voir statistiques"), KeyboardButton("🏦 Solde"))
    markup.add(KeyboardButton("➕ Ajouter bankroll"))  # Nouveau bouton
    markup.add(KeyboardButton("♻️ Réinitialiser bankroll"))  # Bouton pour réinitialiser la bankroll
    markup.add(KeyboardButton("💳 Retrait"))  # Bouton pour effectuer un retrait
    markup.add(KeyboardButton("💾 Sauvegarder Bankroll"), KeyboardButton("📂 Charger Bankroll"))  # Sauvegarde et chargement
    markup.add(KeyboardButton("↩️ Retour"))
    
    bot.send_message(
        message.chat.id,
        "💵 **Gestion de votre Bankroll** 💵\n\nSélectionnez une option :",
        parse_mode="Markdown",
        reply_markup=markup
    )


# Fonction pour sauvegarder les paris en attente
@bot.message_handler(func=lambda msg: msg.text == "💾 Sauvegarder Paris en Attente")
def save_pending_bets_action(message):
    """Sauvegarde les paris en attente dans le fichier JSON."""
    save_pending_bets()
    bot.send_message(message.chat.id, "💾 Paris en attente sauvegardés avec succès ✅ !")

# Fonction pour charger les paris en attente depuis le fichier JSON
@bot.message_handler(func=lambda msg: msg.text == "📂 Charger Paris en Attente")
def load_pending_bets_action(message):
    """Charge les paris en attente depuis le fichier JSON."""
    load_pending_bets()
    if pending_bets:
        bot.send_message(message.chat.id, f"📂 Paris en attente chargés avec succès ✅ !\n\nVoici les paris en attente :")
        for bet in pending_bets:
            bot.send_message(message.chat.id, f"Mise : {bet['stake']} F CFA | Cote : {bet['odds']} | Statut : {bet['status']}")
    else:
        bot.send_message(message.chat.id, "⚠️ Aucun pari en attente trouvé.")
        
# Fonction pour sauvegarder les paris en attente dans la base de données
@bot.message_handler(func=lambda msg: msg.text == "💾 Sauvegarder Paris en Attente")
def save_pending_bets_action(message):
    """Sauvegarde les paris en attente dans la base de données."""
    save_pending_bets()
    bot.send_message(message.chat.id, "💾 Paris en attente sauvegardés avec succès ✅ !")


# Fonction pour afficher les paris en attente avec des boutons interactifs
@bot.message_handler(func=lambda msg: msg.text == "⏳ Paris en attente")
def view_pending_bets(message):
    """Affiche les paris actuellement en attente avec des boutons pour chaque pari."""
    try:
        global pending_bets
        load_pending_bets()  # Charger les paris en attente
        
        if not pending_bets:
            bot.send_message(message.chat.id, "📭 Aucun pari en attente pour le moment.")
        else:
            markup = ReplyKeyboardMarkup(resize_keyboard=True)
            for idx, bet in enumerate(pending_bets, start=1):
                markup.add(KeyboardButton(f"Pari {idx}: {bet['stake']} F CFA à {bet['odds']} de cote"))
            markup.add(KeyboardButton("↩️ Retour"))
            
            bot.send_message(
                message.chat.id, 
                "Voici vos paris en attente. Sélectionnez-en un pour le mettre à jour.", 
                reply_markup=markup
            )
    except Exception as e:
        bot.send_message(message.chat.id, f"⚠️ Une erreur s'est produite : {e}")


@bot.message_handler(func=lambda msg: msg.text.startswith("Pari"))
def select_bet_to_update(message):
    """Permet à l'utilisateur de sélectionner un pari pour le mettre à jour."""
    try:
        global pending_bets
        parts = message.text.split(":")
        index = int(parts[0].split()[1]) - 1

        if 0 <= index < len(pending_bets):
            selected_bet = pending_bets[index]

            # Créer un clavier pour les options de mise à jour
            markup = ReplyKeyboardMarkup(resize_keyboard=True)
            markup.add("Gagné", "Perdu", "Remboursé")
            markup.add("↩️ Retour")

            # Envoyer les détails du pari et demander une action
            bot.send_message(
                message.chat.id,
                f"🎲 *Pari sélectionné*\n💵 Mise : {selected_bet['stake']} F CFA\n📊 Cote : {selected_bet['odds']:.2f}\n🕒 Statut actuel : En attente\n\nChoisissez le statut :",
                reply_markup=markup,
                parse_mode="Markdown"
            )

            # Enregistrer l'étape suivante pour gérer la mise à jour
            bot.register_next_step_handler(message, update_bet_status, selected_bet)
        else:
            bot.send_message(message.chat.id, "⚠️ Sélection invalide. Veuillez choisir un pari valide.")
    except Exception as e:
        bot.send_message(message.chat.id, f"⚠️ Une erreur s'est produite : {e}")


def update_bet_status(message, bet):
    """Met à jour le statut du pari sélectionné (Gagné, Perdu ou Remboursé) et le retire des paris en attente."""
    status = message.text.strip().lower()

    # Récupérer le type de pari
    bet_type = bet.get("bet_type", "Non spécifié")

    if status == "gagné":
        # Mettre à jour le statut et calculer le profit
        profit = (bet["stake"] * bet["odds"]) - bet["stake"]
        bankroll["balance"] += profit
        bet["status"] = "gagné"
        bankroll["bets"].append({"stake": bet["stake"], "odds": bet["odds"], "result": "G", "profit": profit, "bet_type": bet_type})
        bot.send_message(message.chat.id, f"✅ Pari marqué comme gagné : +{profit:.2f} F CFA 🤑\n💰 Nouveau solde : {bankroll['balance']:.2f} F CFA\nType de pari : *{bet_type}*")

    elif status == "perdu":
        # Mettre à jour le statut et déduire la mise
        bankroll["balance"] -= bet["stake"]
        bet["status"] = "perdu"
        bankroll["bets"].append({"stake": bet["stake"], "odds": bet["odds"], "result": "P", "profit": -bet["stake"], "bet_type": bet_type})
        bot.send_message(message.chat.id, f"❌ Pari marqué comme perdu : -{bet['stake']} F CFA 🥶\n💰 Nouveau solde : {bankroll['balance']:.2f} F CFA\nType de pari : *{bet_type}*")

    elif status == "remboursé":
        # Mettre à jour le statut sans modifier le solde
        bet["status"] = "remboursé"
        bankroll["bets"].append({"stake": bet["stake"], "odds": bet["odds"], "result": "R", "profit": 0, "bet_type": bet_type})
        bot.send_message(message.chat.id, f"♻️ Pari marqué comme remboursé : aucun impact sur votre solde.\n💰 Solde actuel : {bankroll['balance']:.2f} F CFA\nType de pari : *{bet_type}*")

    else:
        bot.send_message(message.chat.id, "⚠️ Statut invalide. Veuillez entrer 'Gagné', 'Perdu' ou 'Remboursé'.")
        return

    # Retirer le pari mis à jour des paris en attente
    pending_bets.remove(bet)
    save_pending_bets()  # Sauvegarder les paris restants
    update_stats()  # Mettre à jour les statistiques

    # Retour au menu
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("⏳ Paris en attente", "↩️ Retour")
    bot.send_message(
        message.chat.id, 
        "✅ Mise à jour terminée. Que souhaitez-vous faire ?", 
        reply_markup=markup
    )

    
# Fonction pour traiter le retrait
@bot.message_handler(func=lambda msg: msg.text == "💳 Retrait")
def withdraw_menu(message):
    """Demande à l'utilisateur combien il souhaite retirer."""
    bot.send_message(message.chat.id, "💬 Combien souhaitez-vous retirer de votre bankroll en F CFA ?")
    bot.register_next_step_handler(message, process_withdrawal)

def process_withdrawal(message):
    """Traite la demande de retrait et met à jour la bankroll."""
    try:
        withdrawal_amount = float(message.text.strip())  # Montant du retrait
        if withdrawal_amount <= 0:
            bot.send_message(message.chat.id, "⚠️ Le montant doit être supérieur à zéro.")
        elif withdrawal_amount > bankroll["balance"]:
            bot.send_message(message.chat.id, "⚠️ Vous n'avez pas suffisamment de fonds pour effectuer ce retrait.")
        else:
            # Met à jour le solde actuel
            bankroll["balance"] -= withdrawal_amount

            # Ajouter à l'historique des retraits (vérifier que "withdrawals" est une liste)
            if "withdrawals" not in bankroll:
                bankroll["withdrawals"] = []  # Crée la liste si elle n'existe pas

            # Ajouter le retrait dans l'historique
            bankroll["withdrawals"].append({"amount": withdrawal_amount})

            # Enregistrer le retrait dans la base de données
            save_withdrawal(withdrawal_amount)

            # Mettre à jour les statistiques après ajout du retrait
            update_stats()

            # Envoyer une confirmation
            bot.send_message(
                message.chat.id,
                f"✅ Retrait effectué avec succès : {withdrawal_amount:.2f} F CFA.\n💰 Nouveau solde : {bankroll['balance']:.2f} F CFA",
                parse_mode="Markdown"
            )

    except ValueError:
        bot.send_message(message.chat.id, "⚠️ Veuillez entrer un montant valide pour le retrait.")

def save_withdrawal(amount):
    """Sauvegarde le retrait dans la base de données."""
    global bankroll
    # Ici tu peux ajouter la logique pour enregistrer le retrait dans ta base de données SQLite
    conn = sqlite3.connect('bankroll.db')
    c = conn.cursor()
    c.execute("INSERT INTO withdrawals (amount) VALUES (?)", (amount,))
    conn.commit()
    conn.close()
    
# Réinitialiser la bankroll (tout effacer)@bot.message_handler(func=lambda msg: msg.text == "♻️ Réinitialiser bankroll")
@bot.message_handler(func=lambda msg: msg.text == "♻️ Réinitialiser bankroll")
def reset_bankroll(message):
    """Réinitialise complètement la bankroll et supprime l'historique des paris et des retraits."""
    # Réinitialiser le solde, les retraits et l'historique des paris
    bankroll["balance"] = 0.0
    bankroll["initial_balance"] = 0.0
    bankroll["withdrawals"] = []
    bankroll["bets"] = []  
    bankroll["pending_bets"] = []  # Réinitialiser les paris en mémoire 

    bot.send_message(message.chat.id, "♻️ Bankroll réinitialisée. Tous les paris et retraits ont été supprimés.", parse_mode="Markdown")
    #rest_withdrawals()
    #rest_pending()
    #reset_bets()
    rest_bankroll()

#Fonction pour ajouter une Bankroll    
@bot.message_handler(func=lambda msg: msg.text == "➕ Ajouter bankroll")
def add_initial_bankroll(message):
    bot.send_message(message.chat.id, "**💬 Entrez votre bankroll initiale en FCFA**:", parse_mode="Markdown")
    bot.register_next_step_handler(message, set_initial_bankroll)

def set_initial_bankroll(message):
    try:
        initial_balance = float(message.text.strip())  # Montant du retrait
        if initial_balance < 0:
            bot.send_message(message.chat.id, "⚠️ Le solde initial ne peut pas être négatif.")
        else:
            bankroll["initial_balance"] = initial_balance  # Stocke la bankroll initiale
            bankroll["balance"] = initial_balance  # Mise à jour du solde actuel
            bot.send_message(message.chat.id, f"💰 Votre bankroll initiale a été définie à : {bankroll['balance']:.2f} F CFA")
    except ValueError:
        bot.send_message(message.chat.id, "⚠️ Veuillez entrer un nombre valide pour la bankroll initiale.")
        #sauvegarder Bankroll initial
        save_initial_balance()
# Structure de données pour stocker les paris en attente
pending_bets = []

# Ajouter un pari
@bot.message_handler(func=lambda msg: msg.text == "➕ Ajouter un pari")
def add_bet_prompt(message):
    bot.send_message(
        message.chat.id, 
        "💬 **Entrez les détails du pari au format : montant/cote/résultat (G/P/R), ou laissez vide pour mettre en attente.**",
        parse_mode="Markdown"
    )
    bot.register_next_step_handler(message, add_bet)

def add_bet(message):
    try:
        # Format attendu : montant/cote/résultat
        bet_details = message.text.split("/")

        # Vérifier que l'utilisateur a entré au moins montant et cote
        if len(bet_details) < 2:
            bot.send_message(
                message.chat.id, 
                "⚠️ Format invalide. Veuillez entrer les détails sous la forme : montant/cote/résultat."
            )
            return

        # Conversion en float pour montant et cote
        stake = float(bet_details[0].strip())
        odds = float(bet_details[1].strip())

        # Vérifier que les valeurs sont positives
        if stake <= 0 or odds <= 0:
            bot.send_message(message.chat.id, "⚠️ Montant et cote doivent être des valeurs positives.")
            return

        # Si le résultat est présent
        if len(bet_details) == 3 and bet_details[2].strip() != "":
            result = bet_details[2].strip().lower()

            # Gagné
            if result in ["g", "gagné"]:
                profit = (stake * odds) - stake
                bankroll["balance"] += profit
                bankroll["bets"].append({"stake": stake, "odds": odds, "result": "G", "profit": profit})
                bot.send_message(
                    message.chat.id, 
                    f"✅ **Pari gagné** : +{profit:.2f} F CFA 🤑\n💰 **Nouveau solde** : {bankroll['balance']:.2f} F CFA",
                    parse_mode="Markdown"
                )

            # Perdu
            elif result in ["p", "perdu"]:
                bankroll["balance"] -= stake
                bankroll["bets"].append({"stake": stake, "odds": odds, "result": "P", "profit": -stake})
                bot.send_message(
                    message.chat.id, 
                    f"❌ **Pari perdu** : -{stake:.2f} F CFA 🥶\n💰 **Nouveau solde** : {bankroll['balance']:.2f} F CFA",
                    parse_mode="Markdown"
                )

            # Remboursé
            elif result in ["r", "remboursé"]:
                bankroll["bets"].append({"stake": stake, "odds": odds, "result": "R", "profit": 0.0})
                bot.send_message(
                    message.chat.id, 
                    f"♻️ **Pari remboursé** : aucun changement au solde.\n💰 **Solde actuel** : {bankroll['balance']:.2f} F CFA",
                    parse_mode="Markdown"
                )

            else:
                bot.send_message(message.chat.id, "⚠️ Résultat invalide. Entrez 'G', 'P' ou 'R'.")
        else:
            # Pari mis en attente
            pending_bets.append({"stake": stake, "odds": odds, "status": "en attente"})
            save_pending_bets()  # Sauvegarde les paris en attente

            # Formatage du message pour les paris en attente
            pending_message = (
                "🔔 *Nouveau Pari En Attente* 🔔\n"
                "─────────────────────\n"
                f"💰 *Mise* : {stake:.2f} F CFA\n"
                f"🎲 *Cote* : {odds:.2f}\n"
                "⏳ *Statut* : En Attente\n"
                "─────────────────────\n"
                "✅ *Pari enregistré avec succès*"
            )

            # Envoi du message au bot
            bot.send_message(message.chat.id, pending_message, parse_mode="Markdown")

        # Mettre à jour les statistiques après chaque pari
        update_stats()

    except ValueError:
        bot.send_message(
            message.chat.id, 
            "⚠️ Erreur : veuillez entrer des nombres valides pour le montant et la cote."
        )

    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Une erreur est survenue : {str(e)}")

def update_stats():
    """Met à jour les statistiques."""
    global bankroll

    # Assurer que "withdrawals" est une liste
    if not isinstance(bankroll["withdrawals"], list):
        bankroll["withdrawals"] = []  # Si ce n'est pas une liste, la réinitialiser

    # Inclure les paris en attente dans les statistiques
    total_pending_bets = len(pending_bets)
    total_pending_stake = sum(bet["stake"] for bet in pending_bets)

    # Si aucun pari ou retrait n'existe
    if not bankroll["bets"] and not bankroll["withdrawals"]:
        bankroll["balance"] = bankroll.get("initial_balance", 0)  # Solde = bankroll initiale
        return

    # Calcul des statistiques principales pour les paris terminés
    total_bets = len(bankroll["bets"])
    total_stake = sum(bet["stake"] for bet in bankroll["bets"])
    total_profit = sum(bet["profit"] for bet in bankroll["bets"])
    wins = len([bet for bet in bankroll["bets"] if bet["result"] == "G"])
    losses = len([bet for bet in bankroll["bets"] if bet["result"] == "P"])
    roi = (total_profit / total_stake) * 100 if total_stake > 0 else 0

    # Calcul du solde actuel
    total_withdrawals = sum(w["amount"] for w in bankroll["withdrawals"])
    bankroll["balance"] = bankroll.get("initial_balance", 0) + total_profit - total_withdrawals

    # Afficher les paris en attente
    print(f"Paris en attente: {total_pending_bets}, Mise totale des paris en attente: {total_pending_stake:.2f} F")
    

@bot.message_handler(func=lambda msg: msg.text == "📊 Voir statistiques")
def view_stats(message):
    update_stats() 
    global bankroll  # Accéder à la bankroll globale

    # Vérifier si des données de paris ou de retraits existent
    if not bankroll["bets"] and not bankroll["withdrawals"]:
        bot.send_message(message.chat.id, "📭 Aucun pari ni retrait enregistré pour le moment.")
        return

    # Assurer que 'withdrawals' est une liste
    if not isinstance(bankroll["withdrawals"], list):
        bankroll["withdrawals"] = []  # Réinitialiser en une liste vide si ce n'est pas une liste

    # Initialisation des statistiques
    withdrawals_count = len(bankroll["withdrawals"])
    total_bets = len(bankroll["bets"])
    total_stake = sum(bet["stake"] for bet in bankroll["bets"])
    total_profit = sum(bet["profit"] for bet in bankroll["bets"])
    wins = len([bet for bet in bankroll["bets"] if bet["result"] == "G"])
    losses = len([bet for bet in bankroll["bets"] if bet["result"] == "P"])
    refunds = len([bet for bet in bankroll["bets"] if bet["result"] == "R"])
    roi = (total_profit / total_stake) * 100 if total_stake > 0 else 0

    # Calcul des retraits
    total_withdrawals = sum(w["amount"] for w in bankroll["withdrawals"]) if isinstance(bankroll["withdrawals"], list) else 0
    
    # Calcul de la progression par rapport à la bankroll initiale
    initial_balance = bankroll.get("initial_balance", 0)
    balance_progression = ((bankroll["balance"] - initial_balance) / initial_balance * 100) if initial_balance > 0 else 0

    # Taux de réussite
    success_rate = (wins / total_bets) * 100 if total_bets > 0 else 0

    # Taux d'échec
    failure_rate = (losses / total_bets) * 100 if total_bets > 0 else 0

    # Moyenne des gains et des pertes
    average_profit = total_profit / wins if wins > 0 else 0
    average_loss = abs(total_profit / losses) if losses > 0 else 0

    # Risk-to-Reward Ratio
    risk_to_reward_ratio = average_loss / average_profit if average_profit > 0 else 0

    # Cotes moyennes
    average_odds_wins = sum(bet["odds"] for bet in bankroll["bets"] if bet["result"] == "G") / wins if wins > 0 else 0
    average_odds_losses = sum(bet["odds"] for bet in bankroll["bets"] if bet["result"] == "P") / losses if losses > 0 else 0

    # Meilleur pari gagné et pire pari perdu
    best_win = max([bet for bet in bankroll["bets"] if bet["result"] == "G"], key=lambda x: x["profit"], default=None)
    worst_loss = max([bet for bet in bankroll["bets"] if bet["result"] == "P"], key=lambda x: x["stake"], default=None)

    best_win_profit = best_win["profit"] if best_win else 0
    worst_loss_stake = worst_loss["stake"] if worst_loss else 0
    best_win_odds = best_win["odds"] if best_win else 0
    worst_loss_odds = worst_loss["odds"] if worst_loss else 0

    # Vérification avant la division pour éviter la division par zéro
    average_stake = total_stake / total_bets if total_bets > 0 else 0

    # Génération du message des statistiques
    stats_message = (
        "📊 *Statistiques de la Bankroll* 📊\n"
        "─────────────────────\n"
        f"🏦 *Bankroll initiale* : {initial_balance:.2f} F\n"
        "─────────────────────\n"
        f"💰 *Solde actuel* : {bankroll['balance']:.2f} F\n"
        "─────────────────────\n"
        f"📈 *Rendement total* : {total_profit:.2f} F\n"
        f"📊 *ROI* : {roi:.2f} %\n"
        f"📉 *Progression* : {balance_progression:.2f} %\n"
        "─────────────────────\n"
        f"✅ *Paris gagnés* : {wins}\n"
        f"❌ *Paris perdus* : {losses}\n"
        f"♻️ *Paris remboursés* : {refunds}\n"
        "─────────────────────\n"
        f"✅ *Taux de réussite* : {success_rate:.2f} %\n"
        f"❌ *Taux d'échec* : {failure_rate:.2f} %\n"
        f"📈 *Mise moyenne* : {average_stake:.2f} F\n"
        "─────────────────────\n"
        f"🎯 *Risk-to-Reward Ratio* : {risk_to_reward_ratio:.2f}\n"
        f"🏆 *Cote moyenne gagnants* : {average_odds_wins:.2f}\n"
        f"❌ *Cote moyenne perdants* : {average_odds_losses:.2f}\n"
        "─────────────────────\n"
        f"🔥 *Meilleur pari* : {best_win_profit:.2f} F (Cote : {best_win_odds:.2f})\n"
        f"🥶 *Pire pari* : -{worst_loss_stake:.2f} F (Cote : {worst_loss_odds:.2f})\n"
        "─────────────────────\n"
        f"📋 *Total des paris* : {total_bets}\n"
        f"💵 *Mise totale* : {total_stake:.2f} F\n"
        "─────────────────────\n"
        f"💳 *Total des retraits* : {total_withdrawals:.2f} F (Sur {withdrawals_count} retraits)\n"
        "─────────────────────\n"
    )
    bot.send_message(message.chat.id, stats_message, parse_mode="Markdown")

# Voir historique des paris
@bot.message_handler(func=lambda msg: msg.text == "🗄️ Historique de paris")
def view_history(message):
    if not bankroll["bets"]:
        bot.send_message(message.chat.id, "🗂️ Aucun historique de pari enregistré pour le moment.")
    else:
        # En-tête avec un titre clair
        history = "                     🗃️ Historique des Paris 🗃️\n\n"
        history += "---------------------------------------------\n"
        # Ajouter des en-têtes de colonne pour organiser l'affichage
        history += f"{'🗞️':<4} {'Mise':<10}   {'Cote':<8} {'Résultat':<12} {'Profit':<10}\n"
        history += "---------------------------------------------\n"
        
        # Parcours des paris et ajout des informations dans un format propre
        for idx, bet in enumerate(bankroll["bets"], start=1):
            # Vérifier le statut et ajuster les valeurs en conséquence
            result_display = "Remboursé" if bet["result"] == "R" else ("Gagné" if bet["result"] == "G" else "Perdu")
            profit_display = "0.00 F" if bet["result"] == "R" else f"{bet['profit']:.2f} F"
            
            # Ajout des paris dans l'historique
            history += f"{idx:<4} {bet['stake']:<10}F {bet['odds']:<8} {result_display:<12} {profit_display}\n"

        # Envoi du message avec un format Markdown
        bot.send_message(message.chat.id, history, parse_mode="Markdown")


# Voir le solde actuel
@bot.message_handler(func=lambda msg: msg.text == "🏦 Solde")
def view_balance(message):
    balance = bankroll['balance']
    balance_message = (
        "             🏦 Solde  🏦\n"
        "────────────────\n"
        f"💰 Solde disponible : {balance:.2f} F\n"
        "────────────────"
    )
    bot.send_message(message.chat.id, balance_message, parse_mode="Markdown")


# Fonction pour gérer le retour au menu précédent
@bot.message_handler(func=lambda msg: msg.text == "↩️ Retour")
def back_to_previous_menu(message):
    user_id = message.chat.id

    # Vérifier si l'utilisateur a un menu précédent dans l'historique
    if user_id in user_menu_state and user_menu_state[user_id] is not None:
        previous_menu = user_menu_state[user_id]
        markup = previous_menu
        bot.send_message(message.chat.id, "↩️ Retour au menu précédent :", reply_markup=markup)
    else:
        # Si aucun menu précédent, rediriger vers le menu principal
        markup = create_main_menu()
        bot.send_message(message.chat.id, "🏠 Retour au menu principal :", reply_markup=markup)
        

# Commandes du bot
@bot.message_handler(commands=['start'])
def start(message):
    """Menu de démarrage avec le bouton 🤑 Start 🤑"""
    markup = create_start_menu()
    bot.send_message(
        message.chat.id,
        "🎯 Bienvenue sur le Bot de Prédictions Paris Sportifs ! 💰\n\n"
        "Appuyez sur le bouton 🤑 Start 🤑 pour commencer !",
        reply_markup=markup
    )
# Gestion du bouton 🤑 Start 🤑
@bot.message_handler(func=lambda message: message.text == "🤑 Start 🤑")
def main_menu(message):
    """Affiche le menu principal après avoir cliqué sur 🤑 Start 🤑"""
    markup = create_main_menu()
    bot.send_message(
        message.chat.id,
        "🎯 Bienvenue dans le menu principal !\n\n"
        "Choisissez une option pour continuer :",
        reply_markup=markup
    )


bot.message_handler(func=lambda message: message.text == "↩️ Retour")
def retour_principal(message):
    """Retour au menu principal"""
    current_step["team"] = None
    current_step["data_type"] = None
    start(message)


# Variable pour suivre le menu précédent
previous_menu = None


def create_analyse_menu():
    """Sous-menu Analyse de Match"""
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton("🏠 Domicile"), KeyboardButton("✈️ Extérieur"))
    markup.add(KeyboardButton("📊 Résultats"), KeyboardButton("↩️ Retour "))
    return markup
    

def calculate_draw_half_time_probability(equipe_dom, equipe_ext):
    """Calcule la probabilité pour Nul à la Mi-temps en tenant compte de la forme des équipes"""
    
    # Calculer les moyennes des buts marqués et encaissés à domicile et à l'extérieur
    moyenne_marques_dom = np.mean(equipe_dom['terrain_marques']) if equipe_dom['terrain_marques'] else 0
    moyenne_encaisses_dom = np.mean(equipe_dom['terrain_encaisses']) if equipe_dom['terrain_encaisses'] else 0
    moyenne_marques_ext = np.mean(equipe_ext['terrain_marques']) if equipe_ext['terrain_marques'] else 0
    moyenne_encaisses_ext = np.mean(equipe_ext['terrain_encaisses']) if equipe_ext['terrain_encaisses'] else 0
    
    # Calcul de la probabilité de nul en fonction de la différence de buts
    diff_buts = abs(moyenne_marques_dom - moyenne_marques_ext)
    
    # Ajuster la probabilité en fonction de la différence de buts
    if diff_buts < 1:
        prob_nul = 50  # Haute probabilité de nul si les équipes sont proches
    elif diff_buts < 2:
        prob_nul = 40  # Probabilité de nul modérée si l'écart est faible
    elif diff_buts < 3:
        prob_nul = 30  # Probabilité de nul plus faible avec un écart modéré
    else:
        prob_nul = 25  # Probabilité de nul faible avec une grande différence de buts
    
    
    # Ajouter un facteur de forme basé sur les résultats récents
    forme_dom = np.mean(equipe_dom['globaux_marques']) / np.mean(equipe_dom['globaux_encaisses']) if equipe_dom['globaux_marques'] else 1
    forme_ext = np.mean(equipe_ext['globaux_marques']) / np.mean(equipe_ext['globaux_encaisses']) if equipe_ext['globaux_marques'] else 1
    
    if forme_dom > forme_ext:
        prob_nul -= 6.6  # Moins probable si la forme de l’équipe à domicile est meilleure
    elif forme_dom < forme_ext:
        prob_nul += 6.6  # Plus probable si la forme de l’équipe extérieure est meilleure

    return round(prob_nul, 2)

def calculer_probabilite_buts_non_nuls(buts_moyens):
    """Calcul la probabilité qu'une équipe marque au moins un but."""
    return 1 - np.exp(-buts_moyens)

def probabilites_btts(score_domicile, score_exterieur):
    """Calcule la probabilité des deux équipes marquent (BTTS)."""
    prob_buts_dom = calculer_probabilite_buts_non_nuls(score_domicile)
    prob_buts_ext = calculer_probabilite_buts_non_nuls(score_exterieur)
    p_btts = prob_buts_dom * prob_buts_ext
    return p_btts

def poisson_probability(k, lambda_):
    """Calcule la probabilité de Poisson"""
    return (lambda_ ** k * math.exp(-lambda_)) / math.factorial(k)

def probabilites_over_under(avg_goals):
    """Calcule les probabilités pour Over/Under 2,5 buts."""
    prob_under_2_5 = sum(poisson_probability(k, avg_goals) for k in range(0, 3))  # Probabilité sous 2,5 buts
    prob_over_2_5 = 1 - prob_under_2_5  # Probabilité au-dessus de 2,5 buts
    return prob_over_2_5, prob_under_2_5

def probabilites_over_under_1_5(avg_goals):
    """Calcule les probabilités pour Over/Under 1,5 buts."""
    prob_under_1_5 = sum(poisson_probability(k, avg_goals) for k in range(0, 2))  # Probabilité sous 1,5 buts
    prob_over_1_5 = 1 - prob_under_1_5  # Probabilité au-dessus de 1,5 buts
    return prob_over_1_5, prob_under_1_5
    

# Fonctions de calculs
def calculate_xg(data):
    """Calcule les Expected Goals (xG) d'une équipe."""
    global_marques = data['globaux_marques']
    global_encaisses = data['globaux_encaisses']
    terrain_marques = data['terrain_marques']
    terrain_encaisses = data['terrain_encaisses']
    
    xg_for = (np.mean(global_marques) + np.mean(terrain_marques)) / 2 if global_marques and terrain_marques else 0
    xg_against = (np.mean(global_encaisses) + np.mean(terrain_encaisses)) / 2 if global_encaisses and terrain_encaisses else 0
    
    return round(xg_for, 2), round(xg_against, 2)

def calculate_goal_percentages(data):
    """Calcule les pourcentages de buts marqués et encaissés."""
    total_marques = sum(data['globaux_marques'])
    total_encaisses = sum(data['globaux_encaisses'])
    total_matches = len(data['globaux_marques']) if data['globaux_marques'] else 1  # Éviter la division par zéro
    
    pct_marques = (total_marques / (total_matches * 2)) * 100  # Moyenne sur les matchs
    pct_encaisses = (total_encaisses / (total_matches * 2)) * 100
    
    return round(pct_marques, 2), round(pct_encaisses, 2)



def analyser_forme(scores_marques, scores_encaisses):
    """
    Analyse la forme d'une équipe en se basant sur les scores marqués et encaissés.
    :param scores_marques: Liste des buts marqués sur les 5 derniers matchs.
    :param scores_encaisses: Liste des buts encaissés sur les 5 derniers matchs.
    :return: Dictionnaire contenant les statistiques détaillées.
    """
    if not scores_marques or not scores_encaisses:
        return {
            "forme": 0,
            "pourcentage": 0,
            "classement": "Aucune donnée",
            "resultats": {"victoires": 0, "defaites": 0, "nuls": 0, "details": ""}
        }

    victoires = 0
    defaites = 0
    nuls = 0
    resultats_details = []

    for marques, encaisses in zip(scores_marques[-5:], scores_encaisses[-5:]):
        if marques > encaisses:
            victoires += 1
            resultats_details.append("🏆")
        elif marques == encaisses:
            nuls += 1
            resultats_details.append("🤝🏾")
        else:
            defaites += 1
            resultats_details.append("❌")

    # Calculer les points obtenus
    points = victoires * 3 + nuls * 1
    max_points = 5 * 3
    pourcentage = (points / max_points) * 100

    # Déterminer le classement
    if pourcentage >= 75:
        classement = "🔥"
    elif pourcentage >= 50:
        classement = "✅"
    elif pourcentage >= 25:
        classement = "⚠️"
    else:
        classement = "❌"

    return {
        "forme": points,
        "pourcentage": round(pourcentage, 2),
        "classement": classement,
        "resultats": {
            "victoires": victoires,
            "defaites": defaites,
            "nuls": nuls,
            "details": " ".join(resultats_details)
        }
    }

# Fonctions de gestion des étapes
def start_data_collection(chat_id, team):
    """Commencer la saisie des données pour une équipe"""
    current_step["team"] = team
    current_step["data_type"] = data_steps[0]
    bot.send_message(
        chat_id, 
        f"Entrez les **résultats globaux** de l'équipe à {team} (format: X-Y, séparés par des virgules) :", 
        parse_mode="Markdown"
    )

def handle_data_entry(message):
    """Gestion des données saisies par l'utilisateur"""
    team = current_step["team"]
    data_type = current_step["data_type"]

    try:
        if data_type in ["globaux", "terrain"]:
            scores = message.text.split(',')
            for score in scores:
                x, y = map(int, score.strip().split('-'))
                if data_type == "globaux":
                    data[team]['globaux_marques'].append(x)
                    data[team]['globaux_encaisses'].append(y)
                else:
                    data[team]['terrain_marques'].append(x)
                    data[team]['terrain_encaisses'].append(y)

        elif data_type == "cartons":
            cartons = list(map(int, message.text.split(',')))
            data[team]['cartons_jaunes'].extend(cartons)

        elif data_type == "corners":
            corners = list(map(int, message.text.split(',')))
            data[team]['corners'].extend(corners)

        # Passer à l'étape suivante
        next_step_index = data_steps.index(data_type) + 1
        if next_step_index < len(data_steps):
            current_step["data_type"] = data_steps[next_step_index]
            bot.send_message(
                message.chat.id,
                f"Entrez les **{current_step['data_type']}** pour l'équipe à {team} (format: valeurs séparées par des virgules) :",
                parse_mode="Markdown"
            )
        else:
            bot.send_message(message.chat.id, f"✅ Données pour l'équipe à {team} enregistrées. Revenez au menu Analyse de Match.", reply_markup=create_analyse_menu())
            current_step["team"] = None
            current_step["data_type"] = None

    except ValueError:
        bot.send_message(message.chat.id, "Format invalide. Veuillez réessayer.")



# Variables globales pour stocker les données des équipes
data = {
    "domicile": {
        "globaux_marques": [],
        "globaux_encaisses": [],
        "terrain_marques": [],
        "terrain_encaisses": [],
        "cartons_jaunes": [],
        "corners": []
    },
    "exterieur": {
        "globaux_marques": [],
        "globaux_encaisses": [],
        "terrain_marques": [],
        "terrain_encaisses": [],
        "cartons_jaunes": [],
        "corners": []
    }
}

# Gestion du bouton ↩️ Retour
@bot.message_handler(func=lambda message: message.text == "↩️ Retour")
def retour(message):
    """Retour au menu précédent"""
    global previous_menu
    if previous_menu == "analyse":
        markup = create_analyse_menu()
        bot.send_message(
            message.chat.id,
            "💻 Analyse de Match :\n\n1️⃣ Sélectionnez une équipe pour saisir ses données.\n2️⃣ Consultez les résultats une fois les données saisies.\n",
            reply_markup=markup
        )
    else:
        markup = create_main_menu()
        bot.send_message(
            message.chat.id,
            "🎯 Bienvenue dans le menu principal !\n\nChoisissez une option pour continuer :",
            reply_markup=markup
        )


# Section des fonctions utilitaires
def reset_data():
    """Réinitialise les données des équipes."""
    global data
    data = {
        'domicile': {
            'globaux_marques': [],
            'globaux_encaisses': [],
            'terrain_marques': [],
            'terrain_encaisses': [],
            'cartons_jaunes': [],
            'corners': []
        },
        'exterieur': {
            'globaux_marques': [],
            'globaux_encaisses': [],
            'terrain_marques': [],
            'terrain_encaisses': [],
            'cartons_jaunes': [],
            'corners': []
        }
    }


@bot.message_handler(func=lambda message: message.text == "💻 Analyse de Match 💻")
def analyse_match(message):
    """Sous-menu Analyse de Match"""
    global previous_menu
    previous_menu = "analyse"  # Mettre à jour l'état global

    markup = create_analyse_menu()  # Crée le menu d'analyse
    bot.send_message(
        message.chat.id,
        "💻 Analyse de Match :\n\n"
        "1️⃣ Sélectionnez une équipe pour saisir ses données.\n"
        "2️⃣ Consultez les résultats une fois les données saisies.\n",
        reply_markup=markup
    )
    
@bot.message_handler(func=lambda message: message.text == "🏠 Domicile")
def domicile(message):
    start_data_collection(message.chat.id, "domicile")

@bot.message_handler(func=lambda message: message.text == "✈️ Extérieur")
def exterieur(message):
    start_data_collection(message.chat.id, "exterieur")

@bot.message_handler(func=lambda message: current_step["team"] is not None)
def collect_data(message):
    handle_data_entry(message)

@bot.message_handler(func=lambda message: message.text == "📊 Résultats")
def resultat(message):
    """Affiche les résultats basés sur les données collectées."""
    bot.send_message(message.chat.id, "⏳ Veuillez patienter, j'effectue l'analyse des données pour votre pronostic... 🔍")
    
    # Simulation d'un délai pour l'analyse
    time.sleep(3)  # Temps d'attente (3 secondes)

    equipe_dom = data['domicile']
    equipe_ext = data['exterieur']

     # Analyse de la forme des équipes
    forme_dom = analyser_forme(equipe_dom['globaux_marques'], equipe_dom['globaux_encaisses'])
    forme_ext = analyser_forme(equipe_ext['globaux_marques'], equipe_ext['globaux_encaisses'])

    equipe_dom['moyenne_marques'] = np.mean(equipe_dom['globaux_marques']) if equipe_dom['globaux_marques'] else 0
    equipe_dom['moyenne_encaisses'] = np.mean(equipe_dom['globaux_encaisses']) if equipe_dom['globaux_encaisses'] else 0
    equipe_ext['moyenne_marques'] = np.mean(equipe_ext['globaux_marques']) if equipe_ext['globaux_marques'] else 0
    equipe_ext['moyenne_encaisses'] = np.mean(equipe_ext['globaux_encaisses']) if equipe_ext['globaux_encaisses'] else 0

    score_domicile = (equipe_dom['moyenne_marques'] + equipe_ext['moyenne_encaisses']) / 2
    score_exterieur = (equipe_ext['moyenne_marques'] + equipe_dom['moyenne_encaisses']) / 2

    # Calculs des xG et pourcentages
    xg_dom, xg_dom_against = calculate_xg(equipe_dom)
    xg_ext, xg_ext_against = calculate_xg(equipe_ext)
    pct_dom_marques, pct_dom_encaisses = calculate_goal_percentages(equipe_dom)
    pct_ext_marques, pct_ext_encaisses = calculate_goal_percentages(equipe_ext)
                                                                    
    # Calcul des paris
    btts_prob = probabilites_btts(score_domicile, score_exterieur) * 100  # Multiplié par 100 pour obtenir un pourcentage
    over_2_5_prob, under_2_5_prob = probabilites_over_under(score_domicile + score_exterieur)  # Utilisation de la moyenne des buts
    over_1_5_prob, under_1_5_prob = probabilites_over_under_1_5(score_domicile + score_exterieur)  # Utilisation de la moyenne des buts
    draw_half_time_prob = calculate_draw_half_time_probability(equipe_dom, equipe_ext)

# Calcul des cotes implicites
    cotes_btts = 1 / (btts_prob / 100) if btts_prob > 0 else float('inf')
    cotes_over_2_5 = 1 / over_2_5_prob if over_2_5_prob > 0 else float('inf')
    cotes_under_2_5 = 1 / under_2_5_prob if under_2_5_prob > 0 else float('inf')
    cotes_over_1_5 = 1 / over_1_5_prob if over_1_5_prob > 0 else float('inf')
    cotes_under_1_5 = 1 / under_1_5_prob if under_1_5_prob > 0 else float('inf')
    cotes_draw_half_time = 1 / (draw_half_time_prob / 100) if draw_half_time_prob > 0 else float('inf')

# Arrondi des cotes implicites si elles ne sont pas infinies
    cotes_btts = round(cotes_btts, 2) if cotes_btts != float('inf') else "Infini"
    cotes_over_2_5 = round(cotes_over_2_5, 2) if cotes_over_2_5 != float('inf') else "Infini"
    cotes_under_2_5 = round(cotes_under_2_5, 2) if cotes_under_2_5 != float('inf') else "Infini"
    cotes_over_1_5 = round(cotes_over_1_5, 2) if cotes_over_1_5 != float('inf') else "Infini"
    cotes_under_1_5 = round(cotes_under_1_5, 2) if cotes_under_1_5 != float('inf') else "Infini"
    cotes_draw_half_time = round(cotes_draw_half_time, 2) if cotes_draw_half_time != float('inf') else "Infini"


    resultats = (
        f"=============================\n"
        f"                ⚖️ FOOTGENIUS ⚖️\n"
        f"=============================\n"
        f"               **=>SCORE PREDIT<=**\n"
        f"         DOMICILE  {round(score_domicile)} - {round(score_exterieur)}  EXTÉRIEUR \n"
        f"=============================\n"
        f"     => FORME SUR 5 DERNIER MATCH <=\n"
        f"         DOM : {forme_dom['forme']} points, {forme_dom['pourcentage']}%, {forme_dom['classement']}\n"
        f"           Résultats : {forme_dom['resultats']['details']}\n"
        f"         EXT : {forme_ext['forme']} points, {forme_ext['pourcentage']}%, {forme_ext['classement']}\n"
        f"           Résultats : {forme_ext['resultats']['details']}\n"
        f"=============================\n"
        f"      =>EXPECTED GOALS (xG)<=\n"
        f"             DOM : {round(xg_dom, 2)} (contre {round(xg_dom_against, 2)})\n"
        f"             EXT : {round(xg_ext, 2)} (contre {round(xg_ext_against, 2)})\n"
        f"=============================\n"
        f"      =>POURCENTAGE DE BUT<=\n"
        f"         DOM : {round(pct_dom_marques, 2)}% 🎯 | {round(pct_dom_encaisses, 2)}% ❌\n"
        f"         EXT : {round(pct_ext_marques, 2)}% 🎯 | {round(pct_ext_encaisses, 2)}% ❌\n"
        f"=============================\n"
        f"           🟨 CARTON-JAUNE 🟨\n"       
        f"         DOMICILE  {round(np.mean(equipe_dom['cartons_jaunes']) if equipe_dom['cartons_jaunes'] else 0)} - {round(np.mean(equipe_ext['cartons_jaunes']) if equipe_ext['cartons_jaunes'] else 0)}  EXTÉRIEUR\n"
        f"=============================\n"
        f"                 ⛳️ CORNER ⛳️\n"
        f"        DOMICILE  {round(np.mean(equipe_dom['corners']) if equipe_dom['corners'] else 0)} - {round(np.mean(equipe_ext['corners']) if equipe_ext['corners'] else 0)}  EXTÉRIEUR \n"
        f"=============================\n"
        f"         💡PARIS DISPONIBLE💡\n"
        f"   🔰 BTTS (But partout) : {round(btts_prob, 2)}%\n"
        f"   ♻️ Cote implicite BTTS : {cotes_btts}\n"
        f"\n"
        f"   🔰Over 2.5:  🔼{round(over_2_5_prob * 100, 2)}%\n"
        f"   ♻️ Cote implicite Over 2.5 : {cotes_over_2_5}\n"
        f"\n"
        f"   🔰Under 2.5: 🔽{round(under_2_5_prob * 100, 2)}%\n"
        f"   ♻️ Cote implicite Under 2.5 : {cotes_under_2_5}\n"
        f"\n"
        f"   🔰Over 1.5:  🔼{round(over_1_5_prob * 100, 2)}%\n"
        f"   ♻️ Cote implicite Over 1.5 : {cotes_over_1_5}\n"
        f"\n"
        f"   🔰Under 1.5: 🔽{round(under_1_5_prob * 100, 2)}%\n"
        f"   ♻️ Cote implicite Under 1.5 : {cotes_under_1_5}\n"
        f"\n"
        f"   🔰 Nul une Mi-temps : {round(draw_half_time_prob, 2)}%\n"
        f"   ♻️ Cote implicite Nul mi-temps : {cotes_draw_half_time}\n"
        f"=============================\n"
        
    )

    # Envoi du message avec les résultats
    bot.send_message(message.chat.id, resultats, parse_mode="Markdown")

    # Appel à la fonction de réinitialisation
    reset_data()

    # Message de confirmation
    bot.send_message(message.chat.id, "♻️ Données réinitialisées. Vous pouvez entrer de nouvelles données.")

@bot.message_handler(func=lambda message: message.text == "↩️ Retour")
def retour_principal(message):
    """Retour au menu principal"""
    current_step["team"] = None
    current_step["data_type"] = None
    start(message)

@bot.message_handler(func=lambda message: message.text == "❌ Quitter ❌")
def quitter(message):
    """Envoyer un message et revenir au menu principal"""
    bot.send_message(
        message.chat.id,
        "Bonne chance pour vos pronostics ! À bientôt !",
    )
    # Après l'envoi du message, afficher le menu principal
    bot.send_message(
        message.chat.id,
        "Retour au menu principal.",
        reply_markup=create_start_menu()  # Assurez-vous que la fonction `create_start_menu` est définie pour afficher le menu principal
    )

bot.polling()
