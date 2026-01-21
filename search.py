import sys
import uuid
import json
from dharma import common, tei, tree, patch

# Unicode Private Use Area characters for search markers
MARKER_START = "\uE000"
MARKER_END   = "\uE001"

# --- Extraction Logic ---

def extract_text(root: tree.Node):
	"""Extracts text from a node, ensuring a clean structure with a single trailing newline."""
	buf = []
	extract_text_inner(root, buf)
	# Cleanup trailing newlines to avoid duplication
	while buf and buf[-1] == "\n":
		buf.pop()
	buf.append("\n")
	return "".join(str(s) for s in buf)

def extract_text_from_tag(root, buf):
	match root.name:
		case "logical" | "title":
			for node in root:
				extract_text_inner(node, buf)
		case "para":
			for node in root:
				extract_text_inner(node, buf)
			buf.append("\n")
		case "npage" | "nline" | "ncell" | "display":
			pass
		case "span" | "search" | "link":
			for node in root:
				extract_text_inner(node, buf)
		case "split":
			node = root.first("search")
			if node:
				extract_text_inner(node, buf)
		case "verse":
			extract_from_verse(root, buf)
		case "div" if common.to_boolean(root["phantom"]):
			pass
		case "div":
			head = root.first("stuck-child::head")
			for node in root:
				if node is head:
					continue
				extract_text_inner(node, buf)
			buf.append("\n")
		case "note":
			pass
		case "elist":
			extract_from_elist(root, buf)
		case "dlist":
			extract_from_dlist(root, buf)
		case "quote":
			source = root.first("stuck-child::source")
			buf.append("\t")
			for node in root:
				if node is source:
					continue
				extract_text_inner(node, buf)
		case _:
			pass

def extract_from_elist(root, buf):
	labels = generate_list_labels(root)
	for label, item in zip(labels, root.find("item")):
		buf.append(label)
		buf.append(" ")
		for thing in item:
			extract_text_inner(thing, buf)

def extract_from_dlist(root, buf):
	keys = root.find("key")
	values = root.find("value")
	assert len(keys) == len(values)
	for key, value in zip(keys, values):
		tmp = []
		for thing in key:
			extract_text_inner(thing, tmp)
		while tmp and tmp[-1] == "\n":
			tmp.pop()
		buf.extend(tmp)
		buf.append("➤")
		tmp.clear()
		for thing in value:
			extract_text_inner(thing, tmp)
		while tmp and tmp[-1] == "\n":
			tmp.pop()
		buf.extend(tmp)
		buf.append("\n")

def extract_from_verse(root, buf):
	first = True
	for line in root.find("verse-line"):
		if first:
			first = False
		elif common.to_boolean(line["break"]):
			buf.append(" ")
		for child in line:
			extract_text_inner(child, buf)

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

def extract_text_inner(root, buf):
	match root:
		case tree.String():
			buf.append(translate_string(root))
		case tree.Tag():
			extract_text_from_tag(root, buf)
		case tree.Comment():
			pass
		case _:
			raise Exception(f"unexpected: {root!r}")

def translate_string(s):
	tmp = []
	for c in s.data:
		# Normalize straight quotes to curly quotes for indexing consistency
		if c == "'":
			c = "’"
		tmp.append(c)
	return "".join(tmp)

# --- Highlighting Logic (Stream Injection) ---

class Highlighter:
	"""
	Re-traverses the XML tree while consuming the highlighted text stream from Go.
	Injects <match-start id="x"> and <match-end id="x"> tags into the tree.
	"""
	def __init__(self, stream):
		self.stream = stream
		self.cursor = 0
		self.match_counter = 0
		self.id_stack = []
		self.pending_structure = []

	def highlight(self, root: tree.Node):
		self._process(root)

		while self.pending_structure and self.pending_structure[-1] == "\n":
			self.pending_structure.pop()

		self.pending_structure.append("\n")
		self._flush_pending_structure()

	def _process(self, root: tree.Node):
		match root:
			case tree.String():
				self._handle_string(root)
			case tree.Tag():
				self._handle_tag(root)
			case _:
				pass

	def _handle_string(self, node: tree.String):
		self._flush_pending_structure()

		normalized = translate_string(node)
		if not normalized:
			return

		new_nodes = []
		current_text = []

		for char in normalized:
			self._consume_markers_into(new_nodes, current_text)

			if self.cursor >= len(self.stream):
				break

			current_text.append(char)
			self.cursor += 1

		self._consume_markers_into(new_nodes, current_text)

		if new_nodes:
			if current_text:
				new_nodes.append(tree.String("".join(current_text)))
			node.replace_with(*new_nodes)

	def _consume_markers_into(self, nodes_list, current_text_buffer):
		while self.cursor < len(self.stream) and self.stream[self.cursor] in (MARKER_START, MARKER_END):
			marker = self.stream[self.cursor]
			self.cursor += 1

			if current_text_buffer:
				nodes_list.append(tree.String("".join(current_text_buffer)))
				current_text_buffer.clear()

			if marker == MARKER_START:
				self.match_counter += 1
				mid = self.match_counter
				self.id_stack.append(mid)
				# CORRECTION: Utilisation des arguments nommés pour tree.Tag
				nodes_list.append(tree.Tag("match-start", id=str(mid)))
			else:
				if self.id_stack:
					mid = self.id_stack.pop()
					# CORRECTION: Utilisation des arguments nommés pour tree.Tag
					nodes_list.append(tree.Tag("match-end", id=str(mid)))

	def _flush_pending_structure(self):
		while self.pending_structure:
			char = self.pending_structure.pop(0)
			while self.cursor < len(self.stream) and self.stream[self.cursor] in (MARKER_START, MARKER_END):
				m = self.stream[self.cursor]
				if m == MARKER_START:
					self.match_counter += 1
					self.id_stack.append(self.match_counter)
				elif m == MARKER_END and self.id_stack:
					self.id_stack.pop()
				self.cursor += 1

			if self.cursor < len(self.stream) and self.stream[self.cursor] == char:
				self.cursor += 1

	def _handle_tag(self, root: tree.Tag):
		match root.name:
			case "logical" | "title":
				for node in root: self._process(node)

			case "para":
				for node in root: self._process(node)
				self.pending_structure.append("\n")

			case "span" | "search" | "link":
				for node in root: self._process(node)

			case "split":
				search_node = root.first("search")
				if search_node: self._process(search_node)

			case "verse":
				self._handle_verse(root)

			case "div":
				if not common.to_boolean(root["phantom"]):
					head = root.first("stuck-child::head")
					for node in root:
						if node is head: continue
						self._process(node)
					self.pending_structure.append("\n")

			case "elist":
				self._handle_elist(root)

			case "dlist":
				self._handle_dlist(root)

			case "quote":
				source = root.first("stuck-child::source")
				self.pending_structure.append("\t")
				for node in root:
					if node is source: continue
					self._process(node)

			case _:
				pass

	def _handle_verse(self, root):
		first = True
		for line in root.find("verse-line"):
			if first: first = False
			elif common.to_boolean(line["break"]):
				self.pending_structure.append(" ")
			for child in line:
				self._process(child)

	def _handle_elist(self, root):
		labels = generate_list_labels(root)
		for label, item in zip(labels, root.find("item")):
			for c in label: self.pending_structure.append(c)
			self.pending_structure.append(" ")
			for thing in item:
				self._process(thing)

	def _handle_dlist(self, root):
		keys = root.find("key")
		values = root.find("value")
		for key, value in zip(keys, values):
			for thing in key: self._process(thing)
			while self.pending_structure and self.pending_structure[-1] == "\n":
				self.pending_structure.pop()
			self.pending_structure.append("➤")
			for thing in value: self._process(thing)
			while self.pending_structure and self.pending_structure[-1] == "\n":
				self.pending_structure.pop()
			self.pending_structure.append("\n")

# --- Integration ---

def get_identifier(doc):
	ident = doc.first("/document/identifier")
	if ident:
		return ident.text()
	return ""

def get_logical(doc):
	logical = doc.first("/document/edition/logical")
	if not logical:
		return ""
	return extract_text(logical)

def get_title(doc):
	"""Extracts text from all title elements in metadata."""
	title = doc.find("/document/metadata/title")
	return [extract_text(t) for t in title]

def prepare_search_data(doc):
	data = {}
	data["identifier"] = get_identifier(doc)
	data["logical"] = get_logical(doc)
	data["title"] = get_title(doc)
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

	# Serialize list to JSON string for SQLite storage
	search_data["title"] = json.dumps(search_data["title"])

	db = common.db("texts")
	db.execute("""
	insert or replace into documents_search(identifier, logical, title)
	values (:identifier, :logical, :title)""", search_data)

@common.transaction("texts")
def export_search():
	db = common.db("texts")
	records = db.execute("""select * from documents_search
		where identifier glob 'DHARMA_INS*'""").fetchall()

	# Deserialize SQLite string back to list before final JSON export
	output = []
	for r in records:
		row_dict = dict(r)
		if row_dict.get("title"):
			try:
				row_dict["title"] = json.loads(row_dict["title"])
			except json.JSONDecodeError:
				row_dict["title"] = []
		else:
			row_dict["title"] = []
		output.append(row_dict)

	print(json.dumps(output))

def main():
	export_search()

if __name__ == "__main__":
	main()
