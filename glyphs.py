import logging, urllib.parse, posixpath
from dharma import common, texts, tree

_HANDLERS = []

def _handler(path):
	def decorator(f):
		_HANDLERS.append((tree.Node.match_func(path), f))
		return f
	return decorator

class _Renderer(tree.Serializer):

	def __init__(self, input):
		super().__init__()
		self.handlers = _HANDLERS
		self.input = input
		self.heading_level = 1
		self.idents = set()
		self.visited = set()
		self.langs_cache = {}

	def __call__(self):
		self.clear()
		self.dispatch(self.input.root)
		return self.tree

	def dispatch(self, node):
		if node in self.visited:
			return
		match node:
			case tree.Comment() | tree.Instruction():
				return
			case tree.String() | str():
				self.append(node)
				return
			case tree.Tag() | tree.Tree():
				# We deal with this below
				pass
			case _:
				raise Exception(f"unknown {node}")
		for matcher, f in self.handlers:
			if matcher(node):
				break
		else:
			raise Exception
		f(self, node)

	def dispatch_children(self, node):
		for child in node:
			self.dispatch(child)

	def get_lang(self, code) -> tuple[str, str] | tuple[None, None]:
		ret = self.langs_cache.get(code)
		if not ret:
			ret = common.db("texts").execute("""
				select langs_list.id as id, langs_list.name as name
				from langs_by_code join langs_list
					on langs_by_code.id = langs_list.id
				where langs_by_code.id = ?""", (code,)).fetchone()
			self.langs_cache[code] = tuple(ret) if ret else (None, None)
		return ret

	def append_name(self, node):
		self.dispatch_children(node)
		if not node["lang"]:
			return
		_, lang_name = self.get_lang(node["lang"])
		if not lang_name:
			return
		self.append(" [")
		self.append(lang_name)
		self.append("]")

@_handler("teiHeader")
def _handle_nothing(self, node):
	pass

@_handler("hi[@rend='italic']")
@_handler("foreign")
def _handle_italics(self, node):
	self.push("i")
	self.dispatch_children(node)
	self.join()

@_handler("p")
@_handler("ab")
def _handle_para(self, node):
	self.push("p")
	self.dispatch_children(node)
	self.join()

@_handler("div")
def _handle_div(self, div):
	self.heading_level += 1
	head = div.first("stuck-child::head")
	if head:
		self.push(f"h{self.heading_level}")
		self.dispatch_children(head)
		self.join()
		self.visited.add(head)
	self.push("div", class_="card-list")
	self.dispatch_children(div)
	self.join()
	self.heading_level -= 1

@_handler("ref")
@_handler("ptr")
def _handle_ref(self, ref):
	url = ref["target"]
	if not url:
		return self.dispatch_children(ref)
	self.push("a", href=url)
	self.dispatch_children(ref)
	self.join()

@_handler("graphic")
def _handle_graphic(self, node):
	url = node["url"]
	if not url:
		return
	self.push("img", src=url)
	self.join()

@_handler("list")
def _handle_record(self, node):
	"""
	<div class="card">
	<div class="card-heading">NAME1</div>
	<div class="card-body">
	<div class="card-data">
		<div>Alternative Names</div>
		<div>NAME2; NAME3...</div>
		<div>Mapping</div>
		<div>MAPPING</div>
		<div>Identifiers</div>
		<div>IDENT1; IDENT2...</div>
		<div>Description</div>
		<div>DESCRIPTION</div>
	</div>
	</div>
	</div>
	"""
	rec = _fetch_fields(self, node)
	if not rec:
		return
	self.push("div", class_="card glyph-record", id=rec["idents"][0])
	self.push("div", class_="card-heading")
	if len(rec["names"]) == 0:
		self.append(rec["idents"][0])
	else:
		self.append(rec["idents"][0])
		self.append(": ")
		self.append_name(rec["names"][0])
	self.join() # class_="card-heading"
	self.push("div", class_="card-body")
	self.push("div", class_="card-data")
	if rec["description"]:
		self.push("div"); self.append("Description"); self.join()
		self.push("div")
		self.dispatch_children(rec["description"])
		self.join()
	if len(rec["names"]) > 1:
		self.push("div")
		self.append(common.numberize("Alternative Name", len(rec["names"]) - 1))
		self.join()
		self.push("div")
		for i, name in enumerate(rec["names"][1:]):
			if i > 0:
				self.append("; ")
			self.append_name(name)
		self.join()
	if rec["mapping"]:
		self.push("div"); self.append("Mapping"); self.join()
		self.push("div"); self.append(rec["mapping"]); self.join()
	if len(rec["idents"]) > 1:
		self.push("div")
		self.append(common.numberize("Alternative Identifier", len(rec["idents"]) - 1))
		self.join()
		self.push("div")
		for i, ident in enumerate(rec["idents"][1:]):
			if i > 0:
				self.append("; ")
			self.append(ident)
		self.join()
	self.join() # class_="card-data"
	if rec["extra"]:
		self.dispatch_children(rec["extra"])
	if rec["images"]:
		_add_images(self, rec["images"])
	self.join() # class_="card-body"
	self.join() # class_="card"

def _add_images(self, images):
	self.push("div")
	self.push("p", class_="collapsible")
	self.append("Images")
	self.join()
	self.push("div", class_="glyphs-images hidden")
	for url, caption in images:
		self.push("figure")
		self.append(tree.Tag("img", src=url))
		self.push("figcaption")
		self.dispatch_children(caption)
		self.join()
		self.join("figure")
	self.join()
	self.join()

def get_images(record):
	field = get_first_value(record, "images")
	if not field:
		return []
	figures = []
	for figure in field.find("figure"):
		graphic = figure.first("graphic")
		if not graphic or not graphic["url"]:
			continue
		url = graphic["url"]
		caption = figure.first("head")
		figures.append((url, caption))
	return figures

def _fetch_fields(self, record):
	"""
	<list>
		<label>identifier</label><item>danda</item>
		<label>identifier</label><item>dandaPlain</item>
		<label>description</label><item>plain vertical bar</item>
		<label>mapping</label><item>|</item>
	</list>
	"""
	idents = _fetch_idents(self, record)
	if not idents:
		return
	names = get_values(record, "name")
	desc = get_first_value(record, "description")
	if desc and desc.empty:
		desc = None
	mapping = get_first_value(record, "mapping")
	if mapping:
		mapping = mapping.text()
	if not mapping:
		mapping = None
	extra = get_first_value(record, "extra")
	images = get_images(record)
	return {
		"idents": idents,
		"names": names,
		"description": desc,
		"mapping": mapping,
		"extra": extra,
		"images": images,
	}

def _fetch_idents(self, record):
	idents = []
	values = [node.text() for node in get_values(record, "identifier")]
	for ident in values:
		if not ident:
			continue
		if ident in self.idents:
			logging.error(f"duplicate ident {ident!r}")
			continue
		self.idents.add(ident)
		idents.append(ident)
	if not idents:
		logging.error("missing record identifier")
		return
	return idents

@_handler("*")
def _just_dispatch(self, node):
	self.dispatch_children(node)

def process():
	db = common.db("texts")
	f = db.load_file("DHARMA_glyphTaxonomy")
	t = tree.parse_string(f.data)
	r = _Renderer(t)
	return r()

def extract_data(f: texts.File):
	t = tree.parse_string(f.data)
	records = []
	idents = {}
	for record in t.find("//list"):
		process_record(record, records, idents)
	return records, idents

def process_record(record, records, idents):
	id = len(records)
	rec_idents = set()
	for ident in get_values(record, "identifier"):
		ident = ident.text()
		if ident:
			rec_idents.add(ident)
	if not rec_idents:
		logging.error("missing record identifier")
		return
	rec_idents = sorted(rec_idents)
	names = []
	for node in get_values(record, "name"):
		name = node.text()
		if not name:
			continue
		(lang,) = common.db("texts").execute("""
			select id from langs_by_code
			where code = ?""", (node["lang"],)).fetchone() or (None,)
		names.append({"name": name, "lang": lang})
	desc = get_first_value(record, "description")
	if desc:
		desc = desc.text()
	if not desc:
		desc = None
	mapping = get_first_value(record, "mapping")
	if mapping:
		mapping = mapping.text()
	if not mapping:
		mapping = None
	records.append({
		"id": id,
		"idents": rec_idents,
		"names": names,
		"text": mapping,
		"description": desc,
	})
	for ident in rec_idents:
		if ident in idents:
			logging.error(f"duplicate ident {ident!r}")
			continue
		idents[ident] = id

def get(ident):
	db = common.db("texts")
	row = db.execute("""
		select idents, names, text, description
		from glyphs_by_ident natural join glyphs
		where glyphs_by_ident.ident = ?""", (ident,)).fetchone()
	if row:
		return dict(row)

dependencies = {"DHARMA_glyphTaxonomy.xml"}

def update():
	f = texts.save("project-documentation", "DHARMA_glyphTaxonomy.xml")
	records, idents = extract_data(f)
	db = common.db("texts")
	db.execute("delete from glyphs_by_ident")
	db.execute("delete from glyphs")
	for record in records:
		db.execute("""
		insert into glyphs(id, idents, names, text, description)
		values(:id, :idents, :names, :text, :description)""", record)
	for ident, id in idents.items():
		db.execute("insert into glyphs_by_ident(ident, id) values(?, ?)",
			(ident, id))

def get_first_value(record, key):
	ret = get_values(record, key)
	if ret:
		return ret[0]

def get_values(record, key):
	ret = []
	for label in record.find("label"):
		if label.text() == key:
			item = label.first("stuck-following-sibling::item")
			ret.append(item)
	return ret

if __name__ == "__main__":
	@common.transaction("texts")
	def main():
		update()
	main()
