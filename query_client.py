import sys
import os
import requests
import re
import unicodedata
from dharma import tree
import search

GO_SERVER_URL = "http://localhost:8026/search"
# Adjust path according to your setup
XML_STORAGE_PATH = "/home/michael/dharma/texts.hid/"

class Colors:
	MATCH  = '\033[31;1m'  # Bright Red + Bold
	RESET  = '\033[0m'
	DIM    = '\033[34m'    # Dark Blue
	HEADER = '\033[30;1m'  # Black + Bold
	WARN   = '\033[35;1m'  # Magenta

def colorize_xml(xml_str):
	# Colors the <match> tags and their content for terminal output.
	s = re.sub(r'(<match>)', f'{Colors.MATCH}\\1', xml_str)
	s = re.sub(r'(</match>)', f'\\1{Colors.RESET}', s)
	return s

def main():
	if len(sys.argv) < 2:
		print("Usage: python3 query_client.py <query>")
		sys.exit(1)

	raw_query = " ".join(sys.argv[1:])

	# --- Normalization ---
	# Ensure the query is NFC to match the Go server index.
	query = unicodedata.normalize('NFC', raw_query)

	print(f"Searching for: '{query}' (NFC Normalized) ...\n")

	try:
		resp = requests.get(GO_SERVER_URL, params={"q": query})
		resp.raise_for_status()
		results = resp.json()
	except requests.exceptions.RequestException as e:
		print(f"Go Server Error: {e}")
		sys.exit(1)

	if not results:
		print("No results found.")
		return

	docs_found = 0

	for res in results:
		identifier = res['identifier']
		docs_found += 1

		print(f"{Colors.HEADER}{'='*60}{Colors.RESET}")
		print(f"{Colors.HEADER}DOCUMENT: {identifier}{Colors.RESET}")
		print(f"{Colors.HEADER}{'='*60}{Colors.RESET}")

		xml_path = os.path.join(XML_STORAGE_PATH, f"{identifier}.xml")
		if not os.path.exists(xml_path):
			print(f"{Colors.DIM}XML not found: {xml_path}{Colors.RESET}")
			continue

		try:
			doc = tree.parse(xml_path)
		except Exception as e:
			print(f"{Colors.DIM}Parsing error: {e}{Colors.RESET}")
			continue

		# --- Dynamic Field Highlighting ---
		# Iterate over configured fields in search.py to highlight content

		match_found_in_doc = False

		for field_name, xpath in search.SEARCH_FIELDS.items():

			# Get the marked text(s) returned by the Go server
			marked_data = res.get(field_name)

			# Get the local XML nodes corresponding to this field
			xml_nodes = doc.find(xpath)

			if not marked_data or not xml_nodes:
				continue

			# Handle List fields (e.g., Title)
			if isinstance(marked_data, list):
				for i, content_stream in enumerate(marked_data):
					if search.MARKER_START in content_stream and i < len(xml_nodes):
						match_found_in_doc = True
						hl = search.Highlighter(content_stream)
						hl.highlight(xml_nodes[i])
						print(f"{Colors.DIM}[{field_name.capitalize()}]{Colors.RESET} {colorize_xml(xml_nodes[i].xml())}")

			# Handle String fields (e.g., Logical)
			elif isinstance(marked_data, str):
				if search.MARKER_START in marked_data:
					match_found_in_doc = True
					# Usually string fields map to a single node, take the first one
					target_node = xml_nodes[0]
					hl = search.Highlighter(marked_data)
					hl.highlight(target_node)
					print(f"\n{Colors.DIM}[{field_name.capitalize()}]{Colors.RESET}")
					print(colorize_xml(target_node.xml()))

		if not match_found_in_doc:
			print(f"{Colors.WARN}[DEBUG] Document found but no markers in configured fields.{Colors.RESET}")

		print("\n")

	print(f"Total documents displayed: {docs_found}/{len(results)}")

if __name__ == "__main__":
	main()
