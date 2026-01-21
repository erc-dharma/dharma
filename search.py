import sys
import uuid
import json
import unicodedata
from dharma import common, tei, tree, patch

# Unicode Private Use Area characters for search markers
MARKER_START = "\uE000"
MARKER_END   = "\uE001"

# Configuration table mapping search fields to their XPath in the internal XML.
# This serves as the single source of truth for locating content.
SEARCH_FIELDS = {
	"identifier": "/document/identifier",
	"logical":    "/document/edition/logical",
	"title":      "/document/title"
}

def translate_string(s):
	# Normalize strings to NFC to ensure index alignment with Go.
	# Also normalizes apostrophes.
	tmp = []
	for c in s.data:
		if c == "'":
			c = "’"
		tmp.append(c)
	return unicodedata.normalize('NFC', "".join(tmp))

# --- Core Logic: Structure Walker ---

class InternalWalker:
	# This class holds the logic for traversing the DHARMA internal structure.
	# It delegates actions to a handler (Extraction or Highlighting).
	def __init__(self, handler):
		self.handler = handler

	def walk(self, root):
		self._walk_node(root)
		# Handle final virtual newline (syncs with legacy behavior)
		self.handler.on_virtual("\n")

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
				for node in children:
					self._walk_node(node)
			case "para":
				for node in children:
					self._walk_node(node)
				self.handler.on_virtual("\n")
			case "split":
				search_node = root.first("search")
				if search_node:
					self._walk_node(search_node)
			case "verse":
				self._handle_verse(root)
			case "div":
				if common.to_boolean(root["phantom"]):
					self.handler.on_skipped_node(root)
				else:
					head = root.first("stuck-child::head")
					for node in children:
						if node is head:
							continue
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
					if node is source:
						continue
					self._walk_node(node)
			case "npage" | "nline" | "ncell" | "display" | "note":
				self.handler.on_skipped_node(root)
			case _:
				# Fallback: traverse children
				for node in children:
					self._walk_node(node)

	def _handle_verse(self, root):
		first = True
		for line in root.find("verse-line"):
			if first:
				first = False
			elif common.to_boolean(line["break"]):
				self.handler.on_virtual(" ")
			for child in list(line):
				self._walk_node(child)

	def _handle_elist(self, root):
		labels = generate_list_labels(root)
		for label, item in zip(labels, root.find("item")):
			for c in label: self.handler.on_virtual(c)
			self.handler.on_virtual(" ")
			for thing in list(item):
				self._walk_node(thing)

	def _handle_dlist(self, root):
		keys = root.find("key")
		values = root.find("value")
		for key, value in zip(keys, values):
			for thing in list(key):
				self._walk_node(thing)
			self.handler.on_virtual("➤")
			for thing in list(value):
				self._walk_node(thing)
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
		case _:
			raise Exception(f"bad value: {node!r}")

# --- Handler 1: Text Extraction ---

class TextExtractor:
	def __init__(self):
		self.buf = []

	def on_text(self, node):
		self.buf.append(translate_string(node))

	def on_virtual(self, char):
		self.buf.append(char)

	def on_skipped_node(self, node):
		pass

	def get_result(self):
		while self.buf and self.buf[-1] == "\n":
			self.buf.pop()
		self.buf.append("\n")
		return "".join(str(s) for s in self.buf)

def extract_text(root: tree.Node):
	handler = TextExtractor()
	walker = InternalWalker(handler)
	walker.walk(root)
	return handler.get_result()

# --- Handler 2: Highlighting ---

class Highlighter:
	def __init__(self, marked_stream):
		self.hit_ranges = self._extract_hit_ranges(marked_stream)
		self.cursor = 0

	def highlight(self, root: tree.Node):
		if not self.hit_ranges:
			return
		walker = InternalWalker(self)
		walker.walk(root)

	def _extract_hit_ranges(self, stream):
		ranges = []
		stack = []
		clean_idx = 0
		i = 0
		while i < len(stream):
			char = stream[i]
			if char == MARKER_START:
				stack.append(clean_idx)
			elif char == MARKER_END:
				if stack:
					start = stack.pop()
					ranges.append((start, clean_idx))
			else:
				clean_idx += 1
			i += 1
		return sorted(ranges)

	# --- Handler Interface Implementation ---

	def on_virtual(self, char):
		self.cursor += len(char)

	def on_skipped_node(self, node):
		if self._is_inside_match():
			match_node = tree.Tag("match")
			node.replace_with(match_node)
			match_node.append(node)

	def on_text(self, node):
		normalized = translate_string(node)
		length = len(normalized)
		mask = self._compute_mask(length)
		self.cursor += length
		if not any(mask):
			return
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

	# --- Internal Helpers ---

	def _is_inside_match(self):
		for start, end in self.hit_ranges:
			if start <= self.cursor < end:
				return True
		return False

	def _compute_mask(self, node_len):
		mask = [False] * node_len
		node_start = self.cursor
		node_end = self.cursor + node_len
		for hit_start, hit_end in self.hit_ranges:
			inter_start = max(node_start, hit_start)
			inter_end = min(node_end, hit_end)
			if inter_start < inter_end:
				local_start = inter_start - node_start
				local_end = inter_end - node_start
				for k in range(local_start, local_end):
					mask[k] = True
		return mask

	def _flush_buffer(self, nodes, buffer, is_highlighting):
		if not buffer:
			return
		content = "".join(buffer)
		buffer.clear()
		if is_highlighting:
			match_node = tree.Tag("match")
			match_node.append(tree.String(content))
			nodes.append(match_node)
		else:
			nodes.append(tree.String(content))

# --- Integration ---

def prepare_search_data(doc):
	data = {}
	# Iterate over the configuration table to extract data dynamically
	for field, xpath in SEARCH_FIELDS.items():
		nodes = doc.find(xpath)

		if not nodes:
			data[field] = [] if field == "title" else ""
			continue

		if field == "title":
			# Title is a list of strings
			data[field] = [extract_text(n) for n in nodes]
		else:
			# Other fields are single strings (take the first match)
			data[field] = extract_text(nodes[0])

	data["internal"] = doc.xml()
	return data

def add_document(file):
	try:
		doc = tei.process_file(file).to_internal()
	except tree.Error:
		doc = tree.Tree()
		doc.append(tree.Tag("document"))
	data = patch.fetch_file_data(file.name)
	patch.add_file_info(doc, data)
	search_data = prepare_search_data(doc)

	search_data["title"] = json.dumps(search_data["title"])

	db = common.db("texts")
	db.execute("""
	insert or replace
	into documents_search(identifier, logical, title, internal)
	values (:identifier, :logical, :title, :internal)""", search_data)

@common.transaction("texts")
def export_search():
	db = common.db("texts")
	records = db.execute("""select identifier, logical, title
		from documents_search
		where identifier glob 'DHARMA_INS*'""")
	records = [dict(r) for r in records]
	print(common.to_json(records))

def main():
	export_search()

if __name__ == "__main__":
	main()
