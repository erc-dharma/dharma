import sys, collections
from dharma import tree

HANDLERS = []

def handler(path):
	def decorator(f):
		HANDLERS.append((tree.Node.match_func(path), f))
		return f
	return decorator

@handler("page")
def render_page(self, node):
	self.push(tree.Tag("div", class_="page"))
	self.dispatch_children(node)
	self.join()

@handler("page/stuck-child::head")
def render_page_head(self, node):
	self.push(tree.Tag("div", class_="pagelike"))
	self.dispatch_children(node)
	self.join()

@handler("line")
def render_page_line(self, node):
	self.push(tree.Tag(f"p", class_="line"))
	self.dispatch_children(node)
	self.join()

@handler("quote")
def render_quote(self, node):
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
	if self.notes:
		self.push(tree.Tag("div", class_="notes"))
		self.heading_level += 1
		render_head(self, "Notes")
		self.push(tree.Tag("ol"))
		for note in self.notes:
			n = int(note["n"])
			self.push(tree.Tag("li", class_="note", id=f"note-{n}"))
			paras = note.find("para")
			self.push(tree.Tag("p"))
			self.push(tree.Tag("a", class_="note-ref", data_note_n=str(n), href=f"#note-ref-{n}"))
			self.append(f"{n}.")
			self.join()
			self.append(" ")
			self.dispatch_children(paras[0])
			self.join()
			for para in paras[1:]:
				self.dispatch(para)
			self.join()
		self.join() # </ol>
		self.heading_level -= 1
		self.join() # </div>
	self.join()
	self.document.body = self.top

@handler("elist")
def render_list(self, node):
	match node["type"]:
		case "plain":
			self.push(tree.Tag("ul", class_="list list-plain"))
		case "bulleted":
			self.push(tree.Tag("ul", class_="list"))
		case "numbered":
			self.push(tree.Tag("ol", class_="list"))
	for item in node.find("item"):
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
	path = self.pop()
	self.document.path = path

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

@handler("scripts")
def process_scripts(self, node):
	pass

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

edition_tabs = tree.parse_string("""
<ul class="ed-tabs">
	<li id="physical-btn" class="active"><a href="#">Physical</a></li>
	<li id="logical-btn"><a href="#">Logical</a></li>
	<li id="full-btn"><a href="#">Full</a></li>
</ul>""")

@handler("edition")
@handler("translation")
@handler("commentary")
@handler("bibliography")
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

@handler("extra")
def render_extra(self, node):
	self.dispatch_children(node)

def push_heading(self, level: int, class_: list[str] = []):
	class_ = class_.copy()
	if self.toc_depth >= 0 and self.heading_level > self.toc_depth:
		class_.append("skip-toc")
	# HTML headings stop at <h6>. We could do something sensible when
	# heading_level > 6, but this is unlikely to happen, so we just act is
	# if they had a level 6.
	level = min(self.heading_level, 6)
	self.push(tree.Tag(f"h{level}", class_="".join(class_)))

@handler("apparatus")
def render_apparatus(self, node):
	self.heading_level += 1
	self.push("div", class_="apparatus")
	# Heading
	if (head := node.first("head")):
		push_heading(self, self.heading_level, class_=["collapsible"])
		self.dispatch_children(head)
		self.join() # </head>
	# Contents
	self.push("div")
	for child in node:
		if child is not head:
			self.dispatch(child)
	self.join() # </div>
	# End contents
	self.join() # </div class="apparatus"/>
	self.heading_level -= 1

@handler("logical")
@handler("physical")
@handler("full")
def render_edition_display(self, node):
	self.push("div", class_=node.name, id=node.name, data_display=node.name)
	if node.name != "physical":
		self.top["class"] += " hidden"
	self.dispatch_children(node)
	self.join()

@handler("title")
def render_title(self, node):
	self.push(tree.Tree())
	self.dispatch_children(node)
	self.document.titles.append(self.pop())

@handler("dlist")
def render_dlist(self, node):
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
	self.heading_level += 1
	self.dispatch_children(node)
	self.heading_level -= 1

@handler("edition/stuck-child::head")
def render_edition_head(self, node):
	push_heading(self, self.heading_level)
	self.dispatch_children(node)
	self.join()
	self.extend(edition_tabs)

@handler("head")
def render_head(self, node):
	push_heading(self, self.heading_level)
	self.dispatch_children(node)
	self.join()

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

def make_note_ref(self, node, display=None):
	n = int(node["n"])
	if n == len(self.notes) + 1:
		self.notes.append(node)
	else:
		# This should be a note in the edition, which is duplicated
		# in the tree for the 3 displays (physical, logical, full).
		# We only need one version, so ignore the others.
		assert display is not None
		assert n < len(self.notes) + 1, node.xml()
	self.push(tree.Tag("sup"))
	anchor = f"note-ref-{n}"
	if display:
		anchor += f"-{display}"
	self.push(tree.Tag("a", class_="nav-link", href=f"#note-{n}", id=anchor))
	self.append(str(n))
	self.join()
	self.join()

@handler("physical//note")
def render_physical_note_ref(self, node):
	return make_note_ref(self, node, "physical")

@handler("logical//note")
def render_logical_note_ref(self, node):
	return make_note_ref(self, node, "logical")

@handler("full//note")
def render_full_note_ref(self, node):
	return make_note_ref(self, node, "full")

@handler("note")
def render_note_ref(self, node):
	return make_note_ref(self, node)

@handler("span")
def render_span(self, node):
	span = tree.Tag("span", class_=node["class"], data_tip=node["tip"])
	self.push(span)
	self.dispatch_children(node)
	self.join()

@handler("para")
def render_para(self, node):
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
	self.push("div", class_="verse")
	if (head := node.first("stuck-child::head")):
		self.push("div", class_="verse-heading")
		self.dispatch_children(head)
		self.join()
	self.push("div", class_="verse-lines")
	for line in node.find("verse-line"):
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

@handler("*")
def render_tag(self, node):
	assert isinstance(node, tree.Tag)
	print(f"internal2html: UNKNOWN: {node.name}", file=sys.stderr)

class HTMLDocument:

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
		self.body = None
		self.repository = None # paired
		self.identifier = None
		self.commit = None
		self.last_modified_commit = None
		self.path = None

class HTMLRenderer(tree.Serializer):

	def __init__(self, input, handlers=HANDLERS, toc_depth=-1):
		super().__init__()
		self.handlers = handlers
		self.toc_depth = toc_depth
		self.input = input
		self.notes = []
		self.heading_level = 1
		self.document = HTMLDocument()
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
def process(doc: tree.Tree, toc_depth=-1):
	render = HTMLRenderer(doc, toc_depth=toc_depth)
	ret = render()
	return ret

def process_partial(xml):
	render = HTMLRenderer(xml)
	render()
	return render.tree

if __name__ == "__main__":
	import os
	from dharma import texts, tei, common
	@common.transaction("texts")
	def main():
		path = os.path.abspath(sys.argv[1])
		try:
			f = texts.File("/", path)
			doc = tei.process_file(f)
			html = doc.to_html()
			print(html.body.html())
		except BrokenPipeError:
			pass
	main()
