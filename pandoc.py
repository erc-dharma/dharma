"""
For converting an XML document in the internal representation to Pandoc's JSON
format.

The relevant Pandoc documentation is at:
https://hackage-content.haskell.org/package/pandoc-types-1.23.1.1/docs/Text-Pandoc-Definition.html

Possibly interesting output formats:

        pdf plain docx odt

For generating a docx file: python pandoc.py texts/DHARMA_INSVengiCalukya00034.xml | pandoc -fjson --lua-filter=pandoc/filter.lua --reference-doc=pandoc/reference.docx -o tmp.docx

For generating a pdf file: python pandoc.py texts/DHARMA_INSVengiCalukya00034.xml | pandoc -fjson -otmp.pdf --lua-filter=pandoc/filter.lua --template=pandoc/template.tex --pdf-engine=lualatex
"""

import sys, collections, re, datetime, html
from dharma import tree, common, unicode

_HANDLERS = []

def _handler(path):
	def decorator(f):
		_HANDLERS.append((tree.Node.match_func(path), f))
		return f
	return decorator

@_handler("document")
@_handler("full")
@_handler("display")
def _just_dispatch(self, node):
	self.dispatch_children(node)

def _with_color(self, node, color):
	self.push([])
	self.dispatch_children(node)
	self.append({
		"t": "Span",
		"c": [
			["", [], [["color", color]]],
			self.pop(),
		]
	})

def _with_command(self, node, command):
	self.push([])
	self.dispatch_children(node)
	self.append({"t": command, "c": self.pop()})

@_handler("span")
def _handle_span(self, node):
	match node["class"]:
		case "italics" | "title":
			_with_command(self, node, "Emph")
		case "bold" | "grantha":
			_with_command(self, node, "Strong")
		case "sup":
			_with_command(self, node, "Superscript")
		case "sub":
			_with_command(self, node, "Subscript")
		case "smallcaps":
			_with_command(self, node, "SmallCaps")
		case "abbr":
			_with_color(self, node, "brown")
		case "sic":
			_with_color(self, node, "red")
		case "corr":
			_with_color(self, node, "green")
		case "orig":
			_with_color(self, node, "magenta")
		case "reg":
			_with_color(self, node, "blue")
		case "reading":
			self.push([])
			_with_color(self, node, "green")
			self.append({"t": "Emph", "c": self.pop()})
		case "fw-contents":
			_with_color(self, node, "black")
		case "lb":
			_with_color(self, node, "gray")
		case _:
			self.dispatch_children(node)

@_handler("npage")
@_handler("nline")
@_handler("ncell")
def _render_milestone(self, node):
	_with_color(self, node, "gray")

@_handler("quote")
def _render_quote(self, node):
	# Initialize the BlockQuote container list.
	self.push([])
	# Render the source element as the first paragraph if present.
	if (source := node.first("source")):
		para = {"t": "Para", "c": []}
		self.push(para["c"])
		self.dispatch_children(source)
		self.pop()
		self.append(para)
	# Dispatch all other child blocks making up the citation content.
	for child in node:
		if isinstance(child, tree.Tag) and child.name != "source":
			self.dispatch(child)
	self.append({"t": "BlockQuote", "c": self.pop()})

@_handler("edition")
@_handler("translation")
@_handler("commentary")
@_handler("bibliography")
@_handler("apparatus")
@_handler("div")
def _increase_depth(self, node):
	self.heading_level += 1
	self.dispatch_children(node)
	self.heading_level -= 1

@_handler("search")
@_handler("physical")
@_handler("logical")
@_handler("languages")
@_handler("scripts")
@_handler("title")
@_handler("title")
@_handler("creator")
@_handler("citations")
@_handler("summary")
@_handler("hand")
def _just_ignore(self, node):
	pass

@_handler("elist")
def _render_elist(self, node):
	elist = {"t": "BulletList", "c": []}
	self.push(elist["c"])
	for child in node.find("item"):
		self.push([])
		self.dispatch_children(child)
		self.append(self.pop())
	self.pop()
	self.append(elist)

# Helper to extract inline elements for the definition key, since Pandoc needs inlines here.
def _extract_inlines(self, key_node):
	self.push([])
	self.dispatch_children(key_node)
	key_content = self.pop()
	key_inlines = []
	for block in key_content:
		if "c" in block and isinstance(block["c"], list):
			key_inlines.extend(block["c"])
		elif block.get("t") in ("Str", "Space"):
			key_inlines.append(block)
	return key_inlines

@_handler("dlist")
def _render_dlist(self, node):
	# Initialize the DefinitionList Pandoc AST object.
	dlist = {"t": "DefinitionList", "c": []}
	# Iterate properly over the child nodes of dlist (alternating key and value tags).
	children = [child for child in node if isinstance(child, tree.Tag)]
	for i in range(0, len(children), 2):
		key_inlines = _extract_inlines(self, children[i])
		self.push([])
		self.dispatch_children(children[i+1])
		value_blocks = self.pop()
		dlist["c"].append([key_inlines, [value_blocks]])
	self.append(dlist)

@_handler("verse")
def _render_verse(self, node):
	if (head := node.first("head")):
		_with_command(self, head, "Para")
	self.push([])
	for child in node.find("verse-line"):
		self.push([])
		self.dispatch_children(child)
		self.append(self.pop())
	self.append({"t": "LineBlock", "c": self.pop()})

@_handler("split")
def _render_split(self, node):
	display = node.first("display")
	assert display is not None
	self.dispatch(display)

@_handler("para")
def _render_para(self, node):
	para = {"t": "Para", "c": []}
	self.push(para["c"])
	self.dispatch_children(node)
	self.pop()
	self.append(para)

@_handler("note")
def _render_note(self, node):
	note = {"t": "Note", "c": []}
	self.push(note["c"])
	self.dispatch_children(node)
	self.pop()
	self.append(note)

@_handler("link")
def _render_link(self, node):
	target = node["href"]
	if target.startswith("/"):
		target = "https://dharmalekha.info" + target
		target = target.rstrip("/")
	elif target.startswith("#"):
		self.dispatch_children(node)
		return
	self.push([])
	self.dispatch_children(node)
	contents = self.pop()
	self.append({"t": "Link", "c": [["", [], []], contents, [target, ""]]})

@_handler("head")
def _render_header(self, node):
	self.push([])
	self.dispatch_children(node)
	contents = self.pop()
	self.append({"t": "Header", "c": [self.heading_level, ["", [], []], contents]})

@_handler("*")
def _render_tag(self, node):
	assert isinstance(node, tree.Tag)
	print(f"render: UNKNOWN: {node.name}", file=sys.stderr)

def _get_pandoc_api_version(dflt=[1, 23, 1]):
	try:
		res = subprocess.run(["pandoc", "-t", "json"], input="", capture_output=True, text=True, check=True)
		ast = json.loads(res.stdout)
		return ast.get("pandoc-api-version", dflt)
	except Exception:
		return dflt

class _Renderer:

	def __init__(self, input):
		self.handlers = _HANDLERS
		self.input = input
		self.heading_level = 0
		self.visited = set()
		self.document = {
			"pandoc-api-version": _get_pandoc_api_version(),
			"meta": {},
			"blocks": [],
		}
		self.stack = [self.document["blocks"]]
		self.set_title()
		self.set_author()
		self.set_identifier()
		self.set_repository()
		self.set_modified()
		self.set_summary()
		self.set_hand()
		self.append({"t": "HorizontalRule"})

	def set_identifier(self):
		ident = self.input.first("/document/identifier")
		if not ident:
			return
		para = {"t": "Para", "c": []}
		self.push(para["c"])
		self.append_string(f"Identifier: {ident.text()}")
		self.pop()
		self.append(para)

	def set_repository(self):
		repo = self.input.first("/document/repository")
		if not repo:
			return
		para = {"t": "Para", "c": []}
		self.push(para["c"])
		name = repo.first("name").text()
		ident = repo.first("identifier").text()
		self.append_string(f"Repository: {name} ({ident})")
		self.pop()
		self.append(para)

	def set_modified(self):
		commit = self.input.first("/document/commit")
		if not commit:
			return
		last_modified_commit = self.input.first("/document/last-modified-commit")
		assert last_modified_commit
		when = int(commit.first("date").text())
		when_obj = datetime.datetime.fromtimestamp(when).astimezone()
		when_readable = html.escape(when_obj.strftime("%F %R"))
		hash = commit.first("hash").text()[:7]
		when_modified = int(last_modified_commit.first("date").text())
		when_modified = datetime.datetime.fromtimestamp(when_modified).astimezone()
		when_modified = html.escape(when_modified.strftime("%F %R"))
		hash_modified = last_modified_commit.first("hash").text()[:7]
		para = {"t": "Para", "c": []}
		self.push(para["c"])
		self.append_string(f"Commit: {when_readable} ({hash}), last modified {when_modified} ({hash_modified})")
		self.pop()
		self.append(para)

	def set_title(self):
		elem = self.input.first("/document/title")
		if not elem:
			return
		self.push([])
		self.dispatch_children(elem)
		self.document["meta"]["title"] = {
			"t": "MetaInlines",
			"c": self.pop(),
		}

	def set_author(self):
		editors = self.input.find("/document/creator/name")
		if not editors:
			return
		self.push([])
		for i, editor in enumerate(editors):
			if i == 0:
				pass
			elif i == len(editors) - 1:
				self.append_string(" and ")
			else:
				self.append_string(", ")
			self.append_string(editor.text())
		self.document["meta"]["author"] = {
			"t": "MetaInlines",
			"c": self.pop(),
		}

	def set_summary(self):
		node = self.input.first("/document/summary")
		if not node:
			return
		self.push([])
		self.append_string("Summary")
		self.append({"t": "Header", "c": [self.heading_level + 1, ["", [], []], self.pop()]})
		self.dispatch_children(node)

	def set_hand(self):
		node = self.input.first("/document/hand")
		if not node:
			return
		self.push([])
		self.append_string("Palaeographic description")
		self.append({"t": "Header", "c": [self.heading_level + 1, ["", [], []], self.pop()]})
		self.dispatch_children(node)

	def __call__(self):
		self.dispatch(self.input.root)
		return self.document

	def dispatch(self, node):
		if node in self.visited:
			return
		match node:
			case tree.Comment() | tree.Instruction():
				return
			case tree.String() | str():
				self.append_string(node)
				return
			case tree.Tag() | tree.Tree():
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

	def append_string(self, s):
		if isinstance(s, tree.String):
			s = s.data
		for token in re.findall(r"\s+|\S+", s):
			if token.isspace():
				self.append({"t": "Space"})
			else:
				token = token.replace("'", "’") # HACK
				# token = unicode.hyphenate(token)
				# if token in "([{⟨":
				# 	token = "\N{soft hyphen}" + token
				# elif token in ")]}⟩":
				# 	token += "\N{soft hyphen}"
				self.append({"t": "Str", "c": token})

	def append(self, stuff):
		self.stack[-1].append(stuff)

	def push(self, stuff):
		self.stack.append(stuff)

	def pop(self):
		return self.stack.pop()

# We have an XML tree instead of a Document object as input because 1) we will
# need to process an XML tree for highlighting; and 2) because it is more
# convenient to use xpath.
def process(doc: tree.Tree):
	render = _Renderer(doc)
	ret = render()
	return ret

if __name__ == "__main__":
	import os
	from dharma import texts, ingest, common, enrich
	@common.transaction("texts")
	def main():
		path = os.path.abspath(sys.argv[1])
		try:
			f = texts.File("/", path)
			doc = ingest.process_file(f)
			enrich.process(doc)
			file_data = enrich.fetch_file_data(f.name)
			enrich.add_file_info(doc, file_data)
			ret = process(doc)
			print(common.to_json(ret))
		except BrokenPipeError:
			pass
	main()
