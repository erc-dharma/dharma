"""
For converting an XML document in the internal representation to Pandoc's JSON
format.

The relevant Pandoc documentation is at:
https://hackage-content.haskell.org/package/pandoc-types-1.23.1.1/docs/Text-Pandoc-Definition.html


pdf
plain
docx
odt
markdown
html
"""

import sys, collections, re
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
		case _:
			self.dispatch_children(node)

@_handler("npage")
@_handler("nline")
@_handler("ncell")
def _render_milestone(self, node):
	_with_color(self, node, "gray")

@_handler("quote")
def _render_quote(self, node): # XXX check
	_with_command(self, node, "BlockQuote")

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
def _just_ignore(self, node):
	pass

@_handler("elist")
def _render_elist(self, node):
	elist = {"t": "BulletList", "c": []}
	self.push(elist["c"])
	for child in node.find("item"):
		self.dispatch_children(child)
	self.pop()
	self.append(elist)

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

class _Renderer:

	def __init__(self, input):
		self.handlers = _HANDLERS
		self.input = input
		self.heading_level = 1
		self.visited = set()
		self.document = {
			"pandoc-api-version": [1, 23, 1],
			"meta": {},
			"blocks": [],
		}
		self.stack = [self.document["blocks"]]
		self.set_title()
		self.set_author()
		self.set_summary()
		self.set_hand()
		self.append({"t": "HorizontalRule"})

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
		editors = self.input.find("/document/editor/name")
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
				token = unicode.hyphenate(token)
				if token in "([{⟨":
					token = "\N{soft hyphen}" + token
				elif token in ")]}⟩":
					token += "\N{soft hyphen}"
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
			ret = process(doc)
			print(common.to_json(ret))
		except BrokenPipeError:
			pass
	main()
