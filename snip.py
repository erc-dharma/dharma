"""This module is used to produce snippets in search results."""
# TODO this uses much code from render.py, should refactor

import sys, collections, urllib.parse
from dharma import tree

HANDLERS = []

def handler(path):
	def decorator(f):
		HANDLERS.append((tree.Node.match_func(path), f))
		return f
	return decorator

@handler("quote")
def render_quote(self, node):
	if node["match"] != "true":
		return
	self.push(tree.Tag("div", class_="quote"))
	source = node.first("stuck-child::source")
	if source:
		self.visited.add(source)
	self.push(tree.Tag("blockquote"))
	self.dispatch_children(node)
	self.join() # </blockquote>
	if source:
		self.push(tree.Tag("p"))
		self.push(tree.Tag("cite"))
		self.dispatch_children(source)
		self.join() # </cite>
		self.join() # </p>
	self.join() # </div>

@handler("document")
def render_document(self, node):
	self.push(tree.Tag("div", id="inscription-display"))
	self.dispatch_children(node)
	self.join()
	self.document.body = self.top

@handler("elist")
def render_list(self, node):
	if node["match"] != "true":
		return
	match node["type"]:
		case "plain":
			self.push(tree.Tag("ul", class_="list list-plain"))
		case "bulleted":
			self.push(tree.Tag("ul", class_="list"))
		case "numbered":
			self.push(tree.Tag("ol", class_="list"))
	for item in node.find("item"):
		if item["match"] != "true":
			continue
		self.push(tree.Tag("li"))
		self.dispatch_children(item)
		self.join()
	self.join()

paired = collections.namedtuple("paired", "identifier name")

def extract_paired(self, node):
	name = node.first("name")
	if name:
		self.push(tree.Tree())
		self.dispatch_children(name)
		name = self.pop()
	identifier = node.first("identifier")
	if identifier:
		self.push(tree.Tree())
		self.dispatch_children(identifier)
		identifier = self.pop()
	return paired(identifier, name)

commit = collections.namedtuple("commit", "hash date")

@handler("commit")
@handler("last-modified-commit")
def process_commit(self, node):
	hash_ = node.first("hash")
	if hash_:
		self.push(tree.Tree())
		self.dispatch_children(hash_)
		hash_ = self.pop()
	date = node.first("date")
	if date:
		self.push(tree.Tree())
		self.dispatch_children(date)
		date = self.pop()
	data = commit(hash_, date)
	if node.name == "commit":
		self.document.commit = data
	else:
		assert node.name == "last-modified-commit"
		self.document.last_modified_commit = data

@handler("path")
def process_path(self, node):
	self.push(tree.Tree())
	self.dispatch_children(node)
	self.document.path = self.pop()

@handler("repository")
def process_repo(self, node):
	self.document.repository = extract_paired(self, node)

@handler("editor")
def process_editor(self, node):
	self.document.editors.append(extract_paired(self, node))

@handler("languages")
def process_languages(self, node):
	for lang_node in node.find("language"):
		lang = extract_paired(self, lang_node)
		scripts = []
		for script_node in lang_node.find("script"):
			scripts.append(extract_paired(self, script_node))
		self.document.edition_languages.append((lang, scripts))

@handler("identifier")
def render_identifier(self, node):
	self.push(tree.Tree())
	self.dispatch_children(node)
	name = node.name.replace("-", "_")
	setattr(self.document, name, self.pop())

def prepend_to_first_para(t, text):
	if t.empty:
		return
	para = t.first("stuck-child::p")
	if not para:
		para = tree.Tag("p")
		t.prepend(para)
	para.prepend(text)

@handler("summary")
def render_summary(self, node):
	self.push(tree.Tree())
	self.dispatch_children(node)
	self.document.summary = self.pop()
	prepend_to_first_para(self.document.summary, "Summary: ")

@handler("hand")
def render_hand(self, node):
	self.push(tree.Tree())
	self.dispatch_children(node)
	self.document.hand = self.pop()
	prepend_to_first_para(self.document.hand, "Palaeographic description: ")

@handler("edition")
@handler("commentary")
def render_section(self, node):
	self.heading_level += 1
	# XXX not necessarily correct! should use the actual @xml:lang
	# everywhere.
	lang = "en"
	if node.name == "edition":
		lang = "und"
	self.push("div", class_=node.name, lang=lang)
	self.dispatch_children(node)
	self.join()
	self.heading_level -= 1

@handler("logical")
def render_logical_display(self, node):
	if node["match"] != "true":
		return
	self.push("div", class_="logical")
	self.dispatch_children(node)
	self.document.logical = self.pop()

@handler("translation")
@handler("bibliography")
def render_translation(self, node):
	if node["match"] != "true":
		return
	# TODO lang is not necessarily correct, should use the original
	# @xml:lang.
	self.heading_level += 1
	self.push("div", class_=node.name, lang="en")
	self.dispatch_children(node)
	setattr(self.document, node.name, self.pop())
	self.heading_level -= 1

@handler("title")
def render_title(self, node):
	self.push(tree.Tree())
	self.dispatch_children(node)
	self.document.titles.append(self.pop())

@handler("dlist")
def render_dlist(self, node):
	if node["match"] != "true":
		return
	self.push(tree.Tag("dl", class_="list"))
	for child in node.find("*"):
		match child.name:
			case "key":
				self.push(tree.Tag("dt"))
			case "value":
				self.push(tree.Tag("dd"))
			case _:
				assert 0
		self.dispatch_children(child)
		self.join()
	self.join()

@handler("div[@phantom='false']")
def render_div(self, node):
	if node["match"] != "true":
		return
	self.heading_level += 1
	self.dispatch_children(node)
	self.heading_level -= 1

@handler("npage")
@handler("nline")
@handler("ncell")
def render_milestone(self, node):
	match node.name:
		case "npage":
			class_ = "pagelike"
		case "nline":
			class_ = "lb"
		case "ncell":
			class_ = "gridlike"
		case _:
			raise Exception
	self.push(tree.Tag("span", class_=class_))
	self.dispatch_children(node)
	self.join()

@handler("span")
def render_span(self, node):
	span = tree.Tag("span", class_=node["class"], data_tip=node["tip"])
	self.push(span)
	self.dispatch_children(node)
	self.join()

@handler("para")
def render_para(self, node):
	if node["match"] != "true":
		return
	self.push(tree.Tag("p", class_=node["class"], id=node["anchor"]))
	self.dispatch_children(node)
	self.join()

@handler("link")
def render_link(self, node):
	self.push(tree.Tag("a", href=node["href"]))
	self.dispatch_children(node)
	self.join()

@handler("verse")
def render_verse(self, node):
	if node["match"] != "true":
		return
	self.push("div", class_="verse")
	self.push("div", class_="verse-lines")
	for line in node.find("verse-line"):
		if line["match"] != "true":
			continue
		self.push("div", class_="verse-line")
		self.push("p")
		self.dispatch_children(line)
		self.join()
		self.push("span", data_tip="Verse line number")
		self.append(line["n"])
		self.join()
		self.join()
	self.join()
	self.join()

@handler("display")
@handler("div") # phantom divisions
def just_dispatch(self, node):
	self.dispatch_children(node)

@handler("split")
def render_split(self, node):
	display = node.first("display")
	assert display
	self.dispatch_children(display)

@handler("match")
def render_match(self, node):
	if self.query and self.input_identifier:
		ident = urllib.parse.quote(self.input_identifier, safe="")
		query = urllib.parse.quote(self.query, safe="")
		href = f"/texts/{ident}?q={query}&display=logical#{node['id']}"
	else:
		href = "#"
	link = tree.Tag("span", class_="link highlight")
	link["data-tip"] = "See in context"
	link["data-target"] = href
	self.push(link)
	self.dispatch_children(node)
	self.join()

@handler("omission")
def render_omission(self, node):
	span = tree.Tag("span")
	span.append("[\N{horizontal ellipsis}]")
	span["data-tip"] = "Snippet limit"
	self.append(span)

@handler("apparatus")
@handler("physical")
@handler("full")
@handler("note")
@handler("head")
@handler("scripts")
def just_ignore(self, node):
	pass

@handler("*")
def render_tag(self, node):
	assert isinstance(node, tree.Tag)
	print(f"render: UNKNOWN: {node.name}", file=sys.stderr)

class Document:

	def __init__(self):
		# We are using XML trees instead of str, even for basic stuff
		# like repository, because we expect even fields like that to be
		# highlightable in search results; and, for this to be possible,
		# we need to use trees.
		self.titles = []
		self.summary = None
		self.hand = None
		self.editors = []
		self.edition_languages = []
		self.logical = None
		self.translation = None
		self.bibliography = None
		self.repository = paired(identifier="", name="")
		self.identifier = None
		self.commit = None
		self.last_modified_commit = None
		self.path = None

class Renderer(tree.Serializer):

	def __init__(self, input, query=None, toc_depth=-1):
		super().__init__()
		self.handlers = HANDLERS
		self.toc_depth = toc_depth
		self.input = input
		if (ident := input.first("/document/identifier")):
			self.input_identifier = ident.text()
		else:
			self.input_identifier = None
		self.query = query
		self.notes = []
		self.heading_level = 1
		self.document = Document()
		self.visited = set()

	def __call__(self):
		self.clear()
		self.dispatch(self.input.root)
		return self.document

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

# We have an XML tree instead of a Document object as input because 1) we will
# need to process an XML tree for highlighting; and 2) because it is more
# convenient to use xpath.
def process(doc: tree.Tree, toc_depth=-1, query=None):
	render = Renderer(doc, toc_depth=toc_depth, query=query)
	ret = render()
	return ret

if __name__ == "__main__":
	import os
	from dharma import texts, ingest, common, snip, enrich
	@common.transaction("texts")
	def main():
		path = os.path.abspath(sys.argv[1])
		try:
			f = texts.File("/", path)
			doc = ingest.process_file(f)
			enrich.process(doc)
			ret = process(doc)
			print(ret.logical.html())
		except BrokenPipeError:
			pass
	main()
