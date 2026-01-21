import sys
import os
import requests
import json
from dharma import tree
import search  # On importe notre module search.py pour utiliser Highlighter

# Configuration
GO_SERVER_URL = "http://localhost:8026/search"
XML_STORAGE_PATH = "/home/michael/dharma/texts.hid/"

def main():
	# 1. Récupération de la requête utilisateur
	if len(sys.argv) < 2:
		print("Usage: python3 query_client.py <recherche>")
		sys.exit(1)

	query = " ".join(sys.argv[1:])
	print(f"Querying: {query} ...")

	# 2. Interrogation du serveur Go
	try:
		resp = requests.get(GO_SERVER_URL, params={"q": query})
		resp.raise_for_status()
		results = resp.json()
	except requests.exceptions.RequestException as e:
		print(f"Erreur de connexion au serveur Go: {e}")
		sys.exit(1)

	print(f"Trouvé {len(results)} documents.\n")

	# 3. Traitement des résultats
	for res in results:
		identifier = res['identifier']
		marked_logical = res['logical']
		marked_titles = res.get('title', [])

		print(f"{'='*40}")
		print(f"DOCUMENT: {identifier}")
		print(f"{'='*40}")

		# 4. Chargement du XML original
		xml_path = os.path.join(XML_STORAGE_PATH, f"{identifier}.xml")
		if not os.path.exists(xml_path):
			print(f"Attention: Fichier XML introuvable à {xml_path}")
			continue

		try:
			doc = tree.parse(xml_path)
		except Exception as e:
			print(f"Erreur de parsing XML pour {identifier}: {e}")
			continue

		# 5. Injection des marqueurs (Highlighting)

		# A. Traitement de la partie 'logical'
		logical_node = doc.first("/document/edition/logical")
		if logical_node and marked_logical:
			# On instancie le Highlighter avec le flux marqué venant de Go
			hl = search.Highlighter(marked_logical)
			# On lance le processus de réconciliation/injection
			hl.highlight(logical_node)

		# B. Traitement des titres (si présents et marqués)
		# On récupère les noeuds titres dans le même ordre que search.py (get_titles)
		title_nodes = doc.find("/document/metadata/title")
		if marked_titles and len(title_nodes) == len(marked_titles):
			for t_node, t_stream in zip(title_nodes, marked_titles):
				# On ne highlight que si Go a renvoyé des marqueurs dans ce titre
				if search.MARKER_START in t_stream:
					hl_title = search.Highlighter(t_stream)
					hl_title.highlight(t_node)

		# 6. Affichage du résultat (XML transformé)
		# On affiche une portion sélective ou tout le document
		# Pour la démo, affichons le bloc logique s'il existe
		if logical_node:
			print("--- Partie Logique (Extrait XML) ---")
			print(logical_node.xml())
		else:
			print("--- Document complet (Pas de partie logique trouvée) ---")
			# print(doc.xml()) # Décommenter pour voir tout le fichier

		print("\n")

if __name__ == "__main__":
	main()
