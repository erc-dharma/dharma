import sys
import os
import requests
import re
import unicodedata
from dharma import tree
import search

GO_SERVER_URL = "http://localhost:8026/search"
# Ajustez si nécessaire
XML_STORAGE_PATH = "/home/michael/dharma/texts.hid/"

class Colors:
	MATCH  = '\033[31;1m'
	RESET  = '\033[0m'
	DIM    = '\033[34m'
	HEADER = '\033[30;1m'
	WARN   = '\033[35;1m'

def colorize_xml(xml_str):
	s = re.sub(r'(<match-start[^>]*>)', f'{Colors.MATCH}\\1', xml_str)
	s = re.sub(r'(<match-end[^>]*>)', f'\\1{Colors.RESET}', s)
	return s

def main():
	if len(sys.argv) < 2:
		print("Usage: python3 query_client.py <recherche>")
		sys.exit(1)

	raw_query = " ".join(sys.argv[1:])
	# Normalisation NFC de la requête pour matcher l'index
	query = unicodedata.normalize('NFC', raw_query)

	print(f"Recherche de : '{query}' (NFC) ...\n")

	try:
		resp = requests.get(GO_SERVER_URL, params={"q": query})
		resp.raise_for_status()
		results = resp.json()
	except requests.exceptions.RequestException as e:
		print(f"Erreur connexion Go: {e}")
		sys.exit(1)

	if not results:
		print("Aucun résultat.")
		return

	docs_found = 0

	for res in results:
		identifier = res['identifier']
		marked_logical = res['logical']
		marked_titles = res.get('title', [])

		has_logical_match = search.MARKER_START in marked_logical
		matching_title_indices = [i for i, t in enumerate(marked_titles) if search.MARKER_START in t]

		missing_markers = False
		if not has_logical_match and not matching_title_indices:
			missing_markers = True

		docs_found += 1
		print(f"{Colors.HEADER}{'='*60}{Colors.RESET}")
		print(f"{Colors.HEADER}DOCUMENT: {identifier}{Colors.RESET}")

		if missing_markers:
			print(f"{Colors.WARN}[DEBUG] Document trouvé mais pas de marqueurs.{Colors.RESET}")

		print(f"{Colors.HEADER}{'='*60}{Colors.RESET}")

		xml_path = os.path.join(XML_STORAGE_PATH, f"{identifier}.xml")
		if not os.path.exists(xml_path):
			print(f"{Colors.DIM}XML introuvable: {xml_path}{Colors.RESET}")
			continue

		try:
			doc = tree.parse(xml_path)
		except Exception as e:
			print(f"{Colors.DIM}Erreur parsing: {e}{Colors.RESET}")
			continue

		# Titres
		title_nodes = doc.find("/document/title")
		if not title_nodes:
			title_nodes = doc.find("/document/metadata/title")

		for i, t_stream in enumerate(marked_titles):
			if i < len(title_nodes) and search.MARKER_START in t_stream:
				hl = search.Highlighter(t_stream)
				hl.highlight(title_nodes[i])
				print(f"{Colors.DIM}[Titre]{Colors.RESET} {colorize_xml(title_nodes[i].xml())}")

		# Logical
		if has_logical_match:
			logical_node = doc.first("/document/edition/logical")
			if logical_node:
				hl = search.Highlighter(marked_logical)
				hl.highlight(logical_node)
				print(f"\n{Colors.DIM}[Texte Logique]{Colors.RESET}")
				print(colorize_xml(logical_node.xml()))

		print("\n")

	print(f"Total documents affichés : {docs_found}/{len(results)}")

if __name__ == "__main__":
	main()
