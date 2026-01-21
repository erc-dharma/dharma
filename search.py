import uuid
from dharma import common, tei, tree, texts, patch

class DocumentIndexer:
	"""Handles the parsing of DHARMA XML files to produce search-ready text
	and its mapping.
	"""

	def __init__(self):
		self.mapping = []
		self.current_idx = 0
		self.buf = []

	def _append(self, text: str, node: tree.Node, node_type: str = "text"):
		"""Appends text and records its range in the mapping.
		"""
		if not text:
			return
		start = self.current_idx
		self.buf.append(text)
		self.current_idx += len(text.encode("utf-8"))
		self.mapping.append({
			"start": start,
			"end": self.current_idx,
			"node": node,
			"type": node_type
		})

	def extract_text(self, root: tree.Node):
		"""Extracts text while building the offset mapping.
		"""
		self.mapping = []
		self.current_idx = 0
		self.buf = []
		self._extract_inner(root)
		# Clean trailing newlines for a compact index.
		while self.buf and self.buf[-1] == "\n":
			self.buf.pop()
		self.buf.append("\n")
		return "".join(str(s) for s in self.buf)

	def _extract_inner(self, root: tree.Node):
		"""Internal recursive dispatcher for node types.
		"""
		match root:
			case tree.String():
				self._append(root.data, root)
			case tree.Tag():
				self._extract_from_tag(root)

	def _extract_from_tag(self, root: tree.Tag):
		"""Processes XML tags according to their semantic role.
		"""
		match root.name:
			case "logical" | "para" | "span" | "search" | "link":
				for node in root:
					self._extract_inner(node)
				if root.name == "para":
					self._append("\n", root, "structure")
			case "npage" | "nline" | "ncell" | "display" | "note":
				pass
			case "split":
				# split logic: index <search>, map to <split>.
				search_node = root.first("search")
				if search_node:
					txt = search_node.text(space="preserve")
					self._append(txt, root, "split")
			case "verse":
				self._extract_from_verse(root)
			case "div" if common.to_boolean(root["phantom"]):
				pass
			case "div":
				head = root.first("stuck-child::head")
				for node in root:
					if node is head:
						continue
					self._extract_inner(node)
				self._append("\n", root, "structure")
			case "elist":
				labels = self._generate_list_labels(root)
				for label, item in zip(labels, root.find("item")):
					self._append(label + " ", root, "structure")
					for thing in item:
						self._extract_inner(thing)
					self._append("\n", root, "structure")
			case "dlist":
				keys, values = root.find("key"), root.find("value")
				for key, value in zip(keys, values):
					for thing in key: self._extract_inner(thing)
					self._append(" ➤ ", root, "structure")
					for thing in value: self._extract_inner(thing)
					self._append("\n", root, "structure")
			case "quote":
				source = root.first("stuck-child::source")
				self._append("\t", root, "structure")
				for node in root:
					if node is source: continue
					self._extract_inner(node)
			case _:
				raise Exception(f"unsupported: {root.name}")

	def _extract_from_verse(self, root: tree.Tag):
		"""Extracts text from verse-lines.
		"""
		first = True
		for line in root.find("verse-line"):
			assert isinstance(line, tree.Tag)
			if first:
				first = False
			elif common.to_boolean(line["break"]):
				# If there is a word break at the end of this
				# line, add space before it. Otherwise, we will
				# just concatenate the two verse lines.
				self._append(" ", line, "structure")
			for child in line:
				self._extract_inner(child)
		self._append("\n", root, "structure")

	def _generate_list_labels(self, node: tree.Tag):
		"""Generates markers for different list types.
		"""
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

class SnippetGenerator:
	"""Generates highlighted HTML snippets from index offsets.
	"""

	def generate_snippet(self, mapping: list, start: int, end: int) -> str:
		"""Creates a highlighted XML fragment for a match range.
		"""
		target_entry = None
		for entry in mapping:
			if entry['start'] <= start < entry['end']:
				target_entry = entry
				break
		if not target_entry:
			return ""
		context_node = self._find_context(target_entry['node'])
		overlap = [
			e for e in mapping if max(e['start'], start) < min(e['end'], end)
		]
		temp_ids = {}
		for entry in overlap:
			uid = str(uuid.uuid4())
			temp_ids[uid] = entry['type']
			entry['node'].notes['__hi_id__'] = uid
		snippet_copy = context_node.copy()
		self._apply_highlights(snippet_copy, temp_ids)
		for entry in overlap:
			if '__hi_id__' in entry['node'].notes:
				del entry['node'].notes['__hi_id__']
		return snippet_copy.xml(html=True)

	def _find_context(self, node: tree.Node) -> tree.Node:
		"""Finds a suitable block-level container.
		"""
		curr = node
		while curr.parent:
			if isinstance(curr, tree.Tag) and curr.name in (
				'para', 'lg', 'verse', 'ab', 'note', 'item'
			):
				return curr
			curr = curr.parent
		return node.parent or node

	def _apply_highlights(self, node: tree.Node, temp_ids: dict):
		"""Recursively applies <hi> tags to marked nodes.
		"""
		uid = node.notes.get('__hi_id__')
		if uid:
			if temp_ids[uid] == 'split':
				self._highlight_split(node)
			elif temp_ids[uid] == 'text':
				self._highlight_text(node)
			del node.notes['__hi_id__']
		if isinstance(node, tree.Branch):
			for child in list(node):
				self._apply_highlights(child, temp_ids)

	def _highlight_split(self, split_node: tree.Tag):
		"""Replaces <split> with <hi> containing the <display> child.
		"""
		display = split_node.first("display")
		if display:
			hi = tree.Tag("hi", rend="search-match")
			for child in list(display): hi.append(child)
			split_node.replace_with(hi)

	def _highlight_text(self, text_node: tree.String):
		hi = tree.Tag("span", style="search-match")
		text_node.replace_with(hi)
		hi.append(text_node)

def get_identifier(doc):
	"""Retrieves the document identifier from metadata.
	"""
	ident = doc.first("/document/identifier")
	assert ident
	return ident.text() if ident else ""

def get_title(doc):
	"""Retrieves the document title from metadata.
	"""
	return [t.text() for t in doc.find("/document/title")]

def prepare_search_data(doc: tree.Tree):
	"""Prepares flat data for Go and mapping for snippet generation.
	"""
	indexer = DocumentIndexer()
	data = {}
	data["internal"] = doc.xml()
	data["identifier"] = get_identifier(doc)
	data["title"] = get_title(doc)
	# Target the logical view for search.
	logical_node = doc.first("/document/edition/logical")
	if not logical_node:
		data["logical"] = ""
		return data, []
	data["logical"] = indexer.extract_text(logical_node)
	return data, indexer.mapping

def add_document(file: texts.File):
	try:
		doc = tei.process_file(file).to_internal()
	except tree.Error:
		doc = tree.Tag("document").tree
	# XXX just don't bother separating file data from the rest, add all data
	# in patch.py and update the internal schema accordingly.
	patch.add_file_info(doc, patch.fetch_file_data(file.name))
	search_data, _ = prepare_search_data(doc)
	db = common.db("texts")
	db.execute("""insert or replace
		into documents_search(identifier, logical, title, internal)
		values (:identifier, :logical, :title, :internal)""", search_data)

@common.transaction("texts")
def export_corpus():
	db = common.db("texts")
	for row in db.execute("""select * from documents_search
		where identifier glob 'DHARMA_INS*'"""):
		print(common.to_json(row))

if __name__ == "__main__":
	export_corpus()
