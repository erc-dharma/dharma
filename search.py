import sys
import unicodedata
import requests
import io
from dharma import common, ingest, tree, enrich, render

# Unicode Private Use Area characters for search markers
MARKER_START = "\uE000"
MARKER_END = "\uE001"
GO_SERVER_URL = "http://localhost:8026/search"
# Definitions based on internal.rnc (excluding 'head')
BLOCK_TAGS = {"para", "verse", "quote", "dlist", "elist"}
# Structural parents allowed for a snippet root
VALID_PARENTS = {"div", "logical", "hand"}

def translate_char(c):
	match c:
		case "'":
			return "’"
		case "œ":
			return "oe"
		case "æ":
			return "ae"
		case "đ":
			return "d"
		case _:
			return c

def translate_string(s):
	# Normalize strings to NFC to ensure index alignment with Go.
	tmp = []
	for c in s.data:
		c = translate_char(c)
		tmp.append(c)
	return unicodedata.normalize('NFC', "".join(tmp))

class InternalWalker:

	def __init__(self, handler):
		self.handler = handler

	def walk(self, root):
		self._walk_node(root)

	def _walk_node(self, node):
		match node:
			case tree.String():
				self.handler.on_text(node)
			case tree.Tag():
				self._walk_tag(node)

	def _walk_tag(self, root):
		children = list(root)
		if root.name in ["logical", "title", "span", "search", "link", "identifier", "omission"]:
			for node in children: self._walk_node(node)
		elif root.name == "para":
			self._handle_para(children)
		elif root.name == "split":
			self._handle_split(root)
		elif root.name == "verse":
			self._handle_verse(root)
		elif root.name == "div":
			self._handle_div(root, children)
		elif root.name in ["elist", "dlist", "quote"]:
			self._handle_complex_blocks(root, children)
		elif root.name in ["npage", "nline", "ncell", "display", "note"]:
			self.handler.on_skipped_node(root)
		else:
			for node in children: self._walk_node(node)

	def _handle_para(self, children):
		for node in children: self._walk_node(node)
		self.handler.on_virtual("\n")

	def _handle_split(self, root):
		search_node = root.first("search")
		if search_node: self._walk_node(search_node)

	def _handle_div(self, root, children):
		if common.to_boolean(root["phantom"]):
			self.handler.on_skipped_node(root)
			return
		head = root.first("stuck-child::head")
		for node in children:
			if node is head: continue
			self._walk_node(node)
		self.handler.on_virtual("\n")

	def _handle_complex_blocks(self, root, children):
		if root.name == "elist":
			self._handle_elist(root)
		elif root.name == "dlist":
			self._handle_dlist(root)
		elif root.name == "quote":
			source = root.first("stuck-child::source")
			self.handler.on_virtual("\t")
			for node in children:
				if node is source: continue
				self._walk_node(node)

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
		return "".join(str(s) for s in self.buf).rstrip()

def extract_text(root: tree.Node):
	handler = TextExtractor()
	walker = InternalWalker(handler)
	walker.walk(root)
	return handler.get_result()

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
		self._apply_mask(node, normalized, mask)

	def _apply_mask(self, node, text, mask):
		new_nodes = []
		buffer = []
		is_highlighting = mask[0] if mask else False
		for i, char in enumerate(text):
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

class SnippetGenerator:

	def __init__(self, doc, context_chars=60):
		self.doc = doc
		self.context_chars = context_chars
		self.seen_blocks = set()

	def generate(self):
		roots = self._get_roots()
		if not roots: return
		blocks = []
		for root in roots:
			self._collect_blocks_from_root(root, blocks)
		for block in blocks:
			block["snippet"] = "true"
			pruner = BlockPruner(block, self.context_chars)
			pruner.prune()

	def _get_roots(self):
		roots = []
		roots.extend(self.doc.find("/document/edition/logical"))
		roots.extend(self.doc.find("/document/hand"))
		return roots

	def _collect_blocks_from_root(self, root, blocks):
		matches = []
		self._collect_matches(root, matches)
		for m in matches:
			eligible = self._find_eligible_block(m)
			if eligible and id(eligible) not in self.seen_blocks:
				self.seen_blocks.add(id(eligible))
				blocks.append(eligible)

	def _collect_matches(self, n, matches_list):
		if isinstance(n, tree.Tag):
			if n.name == "match":
				matches_list.append(n)
			for child in list(n):
				self._collect_matches(child, matches_list)

	def _find_eligible_block(self, node):
		curr = node
		while curr:
			if curr.name in BLOCK_TAGS:
				parent = curr.parent
				if parent and parent.name in VALID_PARENTS:
					return curr
			curr = curr.parent
		return None

class BlockPruner:

	def __init__(self, block, context_chars):
		self.block = block
		self.context_chars = context_chars
		self.cursor = 0
		self.match_ranges = []
		self.mask = []

	def prune(self):
		total_len = self._scan_matches(self.block, 0)
		self._build_mask(total_len)
		if total_len < (self.context_chars * 3): return
		self.cursor = 0
		self._transform_children(self.block)

	def _scan_matches(self, node, offset):
		length = 0
		if isinstance(node, tree.String):
			return len(str(node))
		elif isinstance(node, tree.Tag):
			if node.name == "match":
				inner_len = 0
				for c in node:
					inner_len += self._scan_matches(c, offset + length + inner_len)
				self.match_ranges.append((offset + length, offset + length + inner_len))
				return inner_len
			for c in node:
				length += self._scan_matches(c, offset + length)
			return length
		return 0

	def _build_mask(self, total_len):
		self.mask = [False] * total_len
		for start, end in self.match_ranges:
			k_start = max(0, start - self.context_chars)
			k_end = min(total_len, end + self.context_chars)
			for i in range(k_start, k_end):
				self.mask[i] = True

	def _transform_children(self, parent):
		new_children = []
		for child in list(parent):
			res = self._transform_node(child)
			for r in res:
				if self._is_omission(r) and new_children and self._is_omission(new_children[-1]):
					for sub in list(r): new_children[-1].append(sub)
				else:
					new_children.append(r)
		parent.clear()
		for c in new_children: parent.append(c)

	def _is_omission(self, node):
		return isinstance(node, tree.Tag) and node.name == "omission"

	def _transform_node(self, node):
		if isinstance(node, tree.String):
			return self._transform_string(node)
		elif isinstance(node, tree.Tag):
			return self._transform_tag(node)
		return [node]

	def _transform_string(self, node):
		text = str(node)
		length = len(text)
		node_start = self.cursor
		self.cursor += length
		node_mask = self.mask[node_start : node_start + length]
		if all(node_mask): return [node]
		if not any(node_mask):
			om = tree.Tag("omission")
			om.append(node)
			return [om]
		return self._split_string_node(text, node_mask)

	def _split_string_node(self, text, node_mask):
		result_nodes = []
		current_segment = []
		keeping = node_mask[0]
		for i, char in enumerate(text):
			if node_mask[i] == keeping:
				current_segment.append(char)
			else:
				self._flush_segment(result_nodes, current_segment, keeping)
				current_segment = [char]
				keeping = not keeping
		self._flush_segment(result_nodes, current_segment, keeping)
		return result_nodes

	def _flush_segment(self, nodes, segment, keeping):
		if not segment: return
		s_node = tree.String("".join(segment))
		if keeping:
			nodes.append(s_node)
		else:
			om = tree.Tag("omission")
			om.append(s_node)
			nodes.append(om)

	def _transform_tag(self, node):
		if node.name == "match":
			self._advance_cursor_recursive(node)
			return [node]
		self._transform_children(node)
		return [node]

	def _advance_cursor_recursive(self, node):
		if isinstance(node, tree.String):
			self.cursor += len(str(node))
		elif isinstance(node, tree.Tag):
			for child in node: self._advance_cursor_recursive(child)

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
		"extractor": extract_one_text("/document/repository/identifier"),
		"type": "string",
		"highlight": "/document/repository/identifier"
	},
	"repo_name": {
		"extractor": extract_one_text("/document/repository/name"),
		"type": "string",
		"highlight": "/document/repository/name"
	},
	"hand": {
		"extractor": extract_one_text("/document/hand"),
		"type": "string",
		"highlight": "/document/hand"
	},
	"author": {
		"extractor": get_flat_people("/document/author"),
		"type": "people",
		"highlight": "/document/author"
	},
	"editor": {
		"extractor": get_flat_people("/document/editor"),
		"type": "people",
		"highlight": "/document/editor"
	},
	"lang": {
		"extractor": get_flat_matrix("/document/languages/language", "script"),
		"type": "matrix",
		"highlight": "/document/languages/language",
		"child": "script"
	},
	"script": {
		"extractor": get_flat_matrix("/document/scripts/script", "language"),
		"type": "matrix",
		"highlight": "/document/scripts/script",
		"child": "language"
	}
}

def query_search_service(query, offset=0, limit=20, sort="title"):
	norm_query = unicodedata.normalize('NFC', query)
	params = {"q": norm_query, "offset": offset, "limit": limit, "sort": sort}
	resp = requests.get(GO_SERVER_URL, params=params)
	resp.raise_for_status()
	data = resp.json()
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
		SnippetGenerator(doc).generate()
		for_html = render.process(doc)
		print(repr(for_html.logical.html()))
		return for_html
	except Exception as e:
		print(f"Error processing match {item.get('ident')}: {e}")
		return None

def _create_result_dict(item, xml_str):
	doc = tree.parse(io.StringIO(xml_str))
	highlight_document(doc, item)
	SnippetGenerator(doc).generate()
	return {
		"ident": item.get("ident"),
		"xml": doc.xml()
	}

def highlight_document(doc, item_data):
	for field, config in SEARCH_CONFIG.items():
		xpath = config.get("highlight")
		if not xpath: continue
		marked_data = item_data.get(field)
		nodes = doc.find(xpath)
		if not marked_data or not nodes: continue
		_dispatch_highlight(nodes, marked_data, config)

def _dispatch_highlight(nodes, marked_data, config):
	if config["type"] == "list" and isinstance(marked_data, list):
		apply_list_highlight(nodes, marked_data)
	elif config["type"] == "matrix" and isinstance(marked_data, list):
		apply_matrix_highlight(nodes, marked_data, config.get("child"))
	elif config["type"] == "people" and isinstance(marked_data, list):
		apply_people_highlight(nodes, marked_data)
	else:
		apply_string_highlight(nodes, marked_data)

def apply_list_highlight(nodes, marked_list):
	for i, content in enumerate(marked_list):
		if MARKER_START in content:
			if i < len(nodes):
				hl = Highlighter(content)
				hl.highlight(nodes[i])

def apply_people_highlight(nodes, flat_list):
	for i, node in enumerate(nodes):
		id_idx = 2 * i
		name_idx = 2 * i + 1
		if id_idx < len(flat_list):
			targets = node.find("identifier")
			if targets: apply_string_highlight(targets, flat_list[id_idx])
		if name_idx < len(flat_list):
			targets = node.find("name")
			if targets: apply_string_highlight(targets, flat_list[name_idx])

def apply_matrix_highlight(nodes, matrix, child_tag):
	for node, row in zip(nodes, matrix):
		if len(row) > 0:
			targets = node.find("identifier")
			if targets: apply_string_highlight(targets, row[0])
		if len(row) > 1:
			targets = node.find("name")
			if targets: apply_string_highlight(targets, row[1])
		if child_tag:
			_apply_matrix_child_highlight(node, row, child_tag)

def _apply_matrix_child_highlight(node, row, child_tag):
	children = node.find(child_tag)
	col = 2
	for child in children:
		if col < len(row):
			targets = child.find("identifier")
			if targets: apply_string_highlight(targets, row[col])
		col += 1
		if col < len(row):
			targets = child.find("name")
			if targets: apply_string_highlight(targets, row[col])
		col += 1

def apply_string_highlight(nodes, marked_string):
	if MARKER_START in marked_string:
		hl = Highlighter(marked_string)
		hl.highlight(nodes[0])

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
		if config["type"] in ["list", "matrix", "people"]:
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

def prepare_search_data(doc):
	data = {}
	for field, config in SEARCH_CONFIG.items():
		extractor = config["extractor"]
		data[field] = extractor(doc)
	data["source"] = doc.xml()
	return data

def cli_search(query):
	print(f"Searching for: '{query}'...\n", file=sys.stderr)
	try:
		results = query_search_service(query, limit=5)
		count = results.get("match_count", 0)
		matches = results.get("matches", [])
		print(f"Total matches found: {count}", file=sys.stderr)
		print("-" * 60, file=sys.stderr)
		for m in matches:
			ident = m.get("ident", "Unknown")
			xml = m.get("xml", "<document></document>")
			xml = tree.parse_string(xml)
			assert isinstance(xml, tree.Node), type(xml)
			print(f"ID: {ident}", file=sys.stderr)
			for snip in xml.find("//*[@snippet]"):
				print(f"{snip.xml()}")
			print("-" * 60, file=sys.stderr)
			sys.exit()
	except Exception as e:
		raise e

def main():
	if len(sys.argv) > 1:
		cli_search(sys.argv[1])
	else:
		print("Please provide a query argument.")

if __name__ == "__main__":
	main()
