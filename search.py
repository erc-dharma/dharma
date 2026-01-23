import unicodedata
import requests
import io
from dharma import common, ingest, tree, enrich, render

# Unicode Private Use Area characters for search markers
MARKER_START = "\uE000"
MARKER_END   = "\uE001"
GO_SERVER_URL = "http://localhost:8026/search"

def translate_string(s):
	# Normalize strings to NFC to ensure index alignment with Go.
	tmp = []
	for c in s.data:
		if c == "'":
			c = "’"
		tmp.append(c)
	return unicodedata.normalize('NFC', "".join(tmp))

# --- Core Logic: Structure Walker & Text Extraction ---

class InternalWalker:
	def __init__(self, handler):
		self.handler = handler

	def walk(self, root):
		self._walk_node(root)
		# Virtual newline handling delegated to block elements
		pass

	def _walk_node(self, node):
		match node:
			case tree.String():
				self.handler.on_text(node)
			case tree.Tag():
				self._walk_tag(node)
			case _:
				pass

	def _walk_tag(self, root):
		children = list(root)
		match root.name:
			case "logical" | "title" | "span" | "search" | "link" | "identifier":
				for node in children: self._walk_node(node)
			case "para":
				for node in children: self._walk_node(node)
				self.handler.on_virtual("\n")
			case "split":
				search_node = root.first("search")
				if search_node: self._walk_node(search_node)
			case "verse":
				self._handle_verse(root)
			case "div":
				if common.to_boolean(root["phantom"]):
					self.handler.on_skipped_node(root)
				else:
					head = root.first("stuck-child::head")
					for node in children:
						if node is head: continue
						self._walk_node(node)
					self.handler.on_virtual("\n")
			case "elist":
				self._handle_elist(root)
			case "dlist":
				self._handle_dlist(root)
			case "quote":
				source = root.first("stuck-child::source")
				self.handler.on_virtual("\t")
				for node in children:
					if node is source: continue
					self._walk_node(node)
			case "npage" | "nline" | "ncell" | "display" | "note":
				self.handler.on_skipped_node(root)
			case _:
				for node in children: self._walk_node(node)

	def _handle_verse(self, root):
		first = True
		for line in root.find("verse-line"):
			if first: first = False
			elif common.to_boolean(line["break"]): self.handler.on_virtual(" ")
			for child in list(line): self._walk_node(child)

	def _handle_elist(self, root):
		labels = generate_list_labels(root)
		for label, item in zip(labels, root.find("item")):
			for c in label: self.handler.on_virtual(c)
			self.handler.on_virtual(" ")
			for thing in list(item): self._walk_node(thing)

	def _handle_dlist(self, root):
		keys = root.find("key")
		values = root.find("value")
		for key, value in zip(keys, values):
			for thing in list(key): self._walk_node(thing)
			self.handler.on_virtual("➤")
			for thing in list(value): self._walk_node(thing)
			self.handler.on_virtual("\n")

def generate_list_labels(node):
	match node["type"]:
		case "plain":
			while True: yield "◦"
		case "bulleted":
			while True: yield "•"
		case "numbered":
			i = 0
			while True:
				i += 1
				yield f"{i}."
		case _: raise Exception(f"bad value: {node!r}")

class TextExtractor:
	def __init__(self): self.buf = []
	def on_text(self, node): self.buf.append(translate_string(node))
	def on_virtual(self, char): self.buf.append(char)
	def on_skipped_node(self, node): pass
	def get_result(self):
		# Only strip trailing whitespace/newlines to preserve start offsets
		# for accurate highlighting if XML has indentation.
		return "".join(str(s) for s in self.buf).rstrip()

def extract_text(root: tree.Node):
	handler = TextExtractor()
	walker = InternalWalker(handler)
	walker.walk(root)
	return handler.get_result()

# --- Highlighting Logic ---

class Highlighter:
	def __init__(self, marked_stream):
		self.hit_ranges = self._extract_hit_ranges(marked_stream)
		self.cursor = 0

	def highlight(self, root: tree.Node):
		if not self.hit_ranges: return
		walker = InternalWalker(self)
		walker.walk(root)

	def _extract_hit_ranges(self, stream):
		ranges = []
		stack = []
		clean_idx = 0
		i = 0
		while i < len(stream):
			char = stream[i]
			if char == MARKER_START: stack.append(clean_idx)
			elif char == MARKER_END:
				if stack: ranges.append((stack.pop(), clean_idx))
			else: clean_idx += 1
			i += 1
		return sorted(ranges)

	def on_virtual(self, char): self.cursor += len(char)

	def on_skipped_node(self, node):
		if self._is_inside_match(): self._highlight_leaves(node)

	def _highlight_leaves(self, node):
		if isinstance(node, tree.String):
			match_node = tree.Tag("match")
			node.replace_with(match_node)
			match_node.append(node)
		elif isinstance(node, tree.Tag):
			if node.name == "search": return
			for child in list(node): self._highlight_leaves(child)

	def on_text(self, node):
		normalized = translate_string(node)
		length = len(normalized)
		mask = self._compute_mask(length)
		self.cursor += length
		if not any(mask): return
		new_nodes = []
		buffer = []
		is_highlighting = mask[0] if mask else False
		for i, char in enumerate(normalized):
			if mask[i] != is_highlighting:
				self._flush_buffer(new_nodes, buffer, is_highlighting)
				is_highlighting = mask[i]
			buffer.append(char)
		self._flush_buffer(new_nodes, buffer, is_highlighting)
		node.replace_with(*new_nodes)

	def _is_inside_match(self):
		for start, end in self.hit_ranges:
			if start <= self.cursor < end: return True
		return False

	def _compute_mask(self, node_len):
		mask = [False] * node_len
		node_start = self.cursor
		node_end = self.cursor + node_len
		for hit_start, hit_end in self.hit_ranges:
			inter_start = max(node_start, hit_start)
			inter_end = min(node_end, hit_end)
			if inter_start < inter_end:
				for k in range(inter_start - node_start, inter_end - node_start):
					mask[k] = True
		return mask

	def _flush_buffer(self, nodes, buffer, is_highlighting):
		if not buffer: return
		content = "".join(buffer)
		buffer.clear()
		if is_highlighting:
			match_node = tree.Tag("match")
			match_node.append(tree.String(content))
			nodes.append(match_node)
		else: nodes.append(tree.String(content))

# --- Specific Extractors ---

def extract_one_text(xpath):
	def extractor(doc):
		nodes = doc.find(xpath)
		return extract_text(nodes[0]) if nodes else ""
	return extractor

def extract_list_text(xpath):
	def extractor(doc):
		return [extract_text(n) for n in doc.find(xpath)]
	return extractor

def get_repo_id(doc):
	nodes = doc.find("/document/repository/identifier")
	return extract_text(nodes[0]) if nodes else ""

def get_repo_name(doc):
	nodes = doc.find("/document/repository/name")
	return extract_text(nodes[0]) if nodes else ""

def get_flat_people(xpath):
	def extractor(doc):
		res = []
		for node in doc.find(xpath):
			id_nodes = node.find("identifier")
			res.append(extract_text(id_nodes[0]) if id_nodes else "")
			name_nodes = node.find("name")
			res.append(extract_text(name_nodes[0]) if name_nodes else "")
		return res
	return extractor

def get_flat_matrix(parent_xpath, child_tag):
	def extractor(doc):
		matrix = []
		for parent in doc.find(parent_xpath):
			row = []
			pid = parent.find("identifier")
			pname = parent.find("name")
			row.append(extract_text(pid[0]) if pid else "")
			row.append(extract_text(pname[0]) if pname else "")
			for child in parent.find(child_tag):
				cid = child.find("identifier")
				cname = child.find("name")
				row.append(extract_text(cid[0]) if cid else "")
				row.append(extract_text(cname[0]) if cname else "")
			matrix.append(row)
		return matrix
	return extractor

# --- Configuration ---

SEARCH_CONFIG = {
	"ident": {
		"extractor": extract_one_text("/document/identifier"),
		"type": "string",
		"highlight": "/document/identifier"
	},
	"logical": {
		"extractor": extract_one_text("/document/edition/logical"),
		"type": "string",
		"highlight": "/document/edition/logical"
	},
	"title": {
		"extractor": extract_list_text("/document/title"),
		"type": "list",
		"highlight": "/document/title"
	},
	"summary": {
		"extractor": extract_one_text("/document/summary"),
		"type": "string",
		"highlight": "/document/summary"
	},
	"repo_id": {
		"extractor": get_repo_id,
		"type": "string",
		"highlight": None
	},
	"repo_name": {
		"extractor": get_repo_name,
		"type": "string",
		"highlight": "/document/repository"
	},
	"hand": {
		"extractor": extract_one_text("/document/handDesc"),
		"type": "string",
		"highlight": "/document/handDesc"
	},
	"author": {
		"extractor": get_flat_people("/document/author"),
		"type": "list",
		"highlight": "/document/author"
	},
	"editor": {
		"extractor": get_flat_people("/document/editor"),
		"type": "list",
		"highlight": "/document/editor"
	},
	"lang": {
		"extractor": get_flat_matrix("/document/languages/language", "script"),
		"type": "matrix",
		"highlight": None
	},
	"script": {
		"extractor": get_flat_matrix("/document/scripts/script", "language"),
		"type": "matrix",
		"highlight": None
	}
}

# --- Service & DB Integration ---

def query_search_service(query, offset=0, limit=20, sort="title"):
	# Normalize query to NFC to match Go index
	norm_query = unicodedata.normalize('NFC', query)
	try:
		params = {"q": norm_query, "offset": offset, "limit": limit, "sort": sort}
		resp = requests.get(GO_SERVER_URL, params=params)
		resp.raise_for_status()
		data = resp.json()
	except requests.exceptions.RequestException:
		return {"query": query, "match_count": 0, "matches": []}
	processed_matches = process_matches(data.get("matches", []))
	return {
		"query": query,
		"match_count": data.get("count", 0),
		"matches": processed_matches,
		"sort": data.get("sort", sort)
	}

def process_matches(raw_matches):
	results = []
	for item in raw_matches:
		processed = process_single_match(item)
		if processed: results.append(processed)
	return results

def process_single_match(item):
	xml_str = item.get("source", "")
	if not xml_str: return None
	try:
		doc = tree.parse(io.StringIO(xml_str))
		highlight_document(doc, item)
		return render.process(doc)
	except Exception as e:
		print(f"Error processing match {item.get('ident')}: {e}")
		return None

def highlight_document(doc, item_data):
	for field, config in SEARCH_CONFIG.items():
		xpath = config.get("highlight")
		if not xpath: continue
		marked_data = item_data.get(field)
		nodes = doc.find(xpath)
		if not marked_data or not nodes: continue

		if config["type"] == "list" and isinstance(marked_data, list):
			apply_list_highlight(nodes, marked_data)
		else:
			apply_string_highlight(nodes, marked_data)

def apply_list_highlight(nodes, marked_list):
	for i, content in enumerate(marked_list):
		if MARKER_START in content:
			if i < len(nodes):
				hl = Highlighter(content)
				hl.highlight(nodes[i])

def apply_string_highlight(nodes, marked_string):
	if MARKER_START in marked_string:
		hl = Highlighter(marked_string)
		hl.highlight(nodes[0])

def prepare_search_data(doc):
	data = {}
	for field, config in SEARCH_CONFIG.items():
		extractor = config["extractor"]
		data[field] = extractor(doc)
	data["source"] = doc.xml()
	return data

def add_document(file):
	try:
		doc = ingest.process_file(file).to_internal()
	except tree.Error:
		doc = tree.Tree()
		doc.append(tree.Tag("document"))
	data = enrich.fetch_file_data(file.name)
	enrich.add_file_info(doc, data)
	search_data = prepare_search_data(doc)
	for field, config in SEARCH_CONFIG.items():
		if config["type"] in ["list", "matrix"]:
			val = search_data.get(field) or []
			search_data[field] = val
	db = common.db("texts")
	db.execute("""
	insert or replace
	into documents_search(
		ident, logical, title, summary, repo_id, repo_name, hand,
		author, editor, lang, script, source
	)
	values (
		:ident, :logical, :title, :summary, :repo_id, :repo_name, :hand,
		:author, :editor, :lang, :script, :source
	)""", search_data)

@common.transaction("texts")
def export_search():
	db = common.db("texts")
	records = db.execute("""select *
		from documents_search
		where ident glob 'DHARMA_INS*'""")
	records = [dict(r) for r in records]
	print(common.to_json(records))

def main():
	export_search()

if __name__ == "__main__":
	main()
