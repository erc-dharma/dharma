"For parsing TEI files into an internal XML representation."

import os, sys, re, html, urllib.parse, posixpath, copy
from dharma import common, prosody, people, tree, gaiji, biblio, languages
from dharma import patch

class Document:

	def __init__(self):
		self.title: list[tree.Tree] = []
		self.summary = tree.Tree()
		self.hand = tree.Tree()
		# One field for each main div.
		self.edition = tree.Tag("edition")
		self.apparatus = tree.Tag("apparatus")
		self.commentary = tree.Tag("commentary")
		self.bibliography = tree.Tag("bibliography")
		self.translation: list[tree.Tag] = []
		"""A single document can have zero or more translations (see
		e.g. DHARMA_INSPallava00002), so the above is a list."""
		self.notes: list[tree.Tree] = []
		"""List of footnotes (`<note>` element in TEI, except that we
		don't include here `<note>` elements from the apparatus because
		they do not actually represent footnotes; we should probably
		support notes within notes in the apparatus, because in this
		case the nesting is justified)."""
		# List of authors and of editors. List of tuples
		# (dharma_id, name) where dharma_id is the xxxx stuff in
		# "part:xxxx" and name is a string.  dharma_id can be None
		self.authors: list[tuple[str, str]] = []
		self.editors: list[tuple[str, str]] = []
		# For bestow.
		self.extra = tree.Tree()

	def serialize(self):
		f = tree.Serializer()
		f.push(tree.Tag("document"))
		for title in self.title:
			f.push(tree.Tag("title"))
			f.extend(title)
			f.join()
		for author_id, author_name in self.authors:
			f.push(tree.Tag("author"))
			assert author_name
			f.push(tree.Tag("name"))
			f.append(author_name)
			f.join()
			if author_id:
				f.push(tree.Tag("identifier"))
				f.append(author_id)
				f.join()
			f.join()
		for editor_id, editor_name in self.editors:
			f.push(tree.Tag("editor"))
			assert editor_name
			f.push(tree.Tag("name"))
			f.append(editor_name)
			f.join()
			if editor_id:
				f.push(tree.Tag("identifier", lang="ident latin"))
				f.append(editor_id)
				f.join()
			f.join()
		if not self.summary.empty:
			f.push(tree.Tag("summary"))
			f.extend(self.summary)
			f.join()
		if not self.hand.empty:
			f.push(tree.Tag("hand"))
			f.extend(self.hand)
			f.join()
		if not self.edition.empty:
			f.append(self.edition)
		if not self.apparatus.empty:
			f.append(self.apparatus)
		for trans in self.translation:
			f.append(trans)
		if not self.commentary.empty:
			f.append(self.commentary)
		if not self.bibliography.empty:
			f.append(self.bibliography)
		if not self.extra.empty:
			f.push(tree.Tag("extra"))
			f.extend(self.extra)
			f.join()
		f.join()
		return f.tree

	def to_internal(self):
		ret = self.serialize()
		patch.process(ret)
		return ret

	def to_html(self, toc_depth=-1, data=None):
		from dharma import internal2html
		ret = self.serialize()
		patch.process(ret)
		if data is not None:
			patch.add_file_info(ret, data)
		ret = internal2html.process(ret, toc_depth=toc_depth)
		return ret

def XML(s):
	r = tree.parse_string(f"<root>{s}</root>")
	r.root.unwrap()
	return r

# Handlers are tested per order of appearance in this file, so the most
# specific ones should come first.
HANDLERS = []

def handler(path):
	def decorator(f):
		HANDLERS.append((tree.Node.match_func(path), f))
		return f
	return decorator

class Parser(tree.Serializer):

	def __init__(self, t, handlers=HANDLERS):
		super().__init__()
		self.handlers = handlers
		self.tree = t
		self.document = Document()
		# Nodes in this set are ignored in dispatch(). These nodes
		# still remain in the tree and are still accessible from
		# within handlers.
		self.visited = set()
		self._prosody_entries = {}
		## Biblio stuff
		# Map of biblio short titles -> bibliography entries. Only
		# includes bibliography entries that appear in the
		# div[@type='bibliography'].
		self.bib_entries: dict[str, tree.Tree] = {}
		# Like bib_entries, but for bibliography entries that are
		# referred to in the file but that do not appear in the
		# div[@type='bibliography'].
		self.external_bib_entries: dict[str, tree.Tree] = {}
		# Map of biblio entry short title (string) -> siglum (string)
		self.sigla: dict[str, str] = {}

	def append_display(self, text, name=None, lang=None):
		assert name is None or name in ("physical", "logical")
		tag = tree.Tag("display", lang=lang or "study_other latin", name=name)
		self.push(tag)
		self.append(text)
		self.join()

	def _get_bib_entry(self, short_title):
		external = False
		entry = self.bib_entries.get(short_title)
		if not entry:
			# It should occur in the global bibliography. We cache
			# the result to ensure we only perform a single database
			# lookup.
			external = True
			entry = self.external_bib_entries.get(short_title)
			if not entry:
				entry = biblio.lookup_entry(short_title)
				self.external_bib_entries[short_title] = entry
		return entry, external

	def bib_entry(self, short_title, location=[]):
		assert short_title
		entry = self.bib_entries.get(short_title)
		if not entry:
			db = common.db("texts")
			# If the entry is in the full biblio_data table but not
			# in the biblio table, it is because the entry has a
			# type we cannot process.
			if db.execute("select 1 from biblio_data where short_title = ?", (short_title,)).fetchone():
				tip = "Unsupported entry type"
			else:
				tip = "Not in bibliography"
			span = tree.Tag("span", class_="invalid", tip=tip)
			span.append(short_title)
			ret = tree.Tag("para", class_="hanging")
			ret.append(span)
			return ret
		siglum = self.sigla.get(short_title)
		# XXX warn about duplicate entries
		return biblio.format_entry(entry, location=location, siglum=siglum)

	def bib_reference(self, short_title, rend="default", location=[], contents=[]):
		entry, external = self._get_bib_entry(short_title)
		if not entry:
			if not short_title:
				short_title = "???"
				tip = "Missing short title"
			elif common.db("texts").execute("select 1 from biblio_data where short_title = ?", (short_title,)).fetchone():
				tip = "Unsupported entry type"
			else:
				tip = "Not in bibliography"
			span = tree.Tag("span", tip=tip)
			span.append(short_title)
			ref = tree.Tag("link")
			ref.append(span)
			return ref
		ref = biblio.format_reference(entry, rend=rend,
			location=location,
			siglum=self.sigla.get(short_title),
			external_link=external,
			contents=contents)
		return ref

	def get_prosody_entry(self, name: str) \
		-> (tuple[tree.Tree | None, str | None, int] | None):
		entry = self._prosody_entries.get(name, object)
		if entry is object:
			# Not yet fetched from the db.
			db = common.db("texts")
			entry = db.execute(
				"""select pattern, description, entry_id
				from prosody where name = ?""",
				(name,)).fetchone() or None
			self._prosody_entries[name] = entry
		if entry:
			pattern, description, entry_id = entry
			if pattern:
				# We do need a new copy in the calling code.
				pattern = tree.parse_string(pattern)
			return pattern, description, entry_id

	def dispatch(self, node):
		if node in self.visited:
			return
		match node:
			case tree.Comment() | tree.Instruction():
				return
			case tree.String():
				# XXX rather do that on the final representation
				self.append(str(node).replace("'", "’"))
				return
			case tree.Tag() | tree.Tree():
				pass
			case _:
				assert 0, repr(node)
		for matcher, f in self.handlers:
			if matcher(node):
				break
		else:
			raise Exception(f"cannot handle {node!r}")
		f(self, node)

	def dispatch_children(self, node):
		for child in node:
			self.dispatch(child)

################################# Links ########################################

# The syntax for ref is <ref target="myurl">foo</ref>, equivalent to the HTML
# <a href="myurl">foo</ref>. <ptr/> is like <ref> except that it is supposed
# to be empty. Even so, we try to deal appropriately with a non-empty <ptr/>.

bibl_units = set(biblio.cited_range_units)

def extract_bibl_ref(bibl, ref):
	# The ptr/@target is supposed to start with "bib:". If it doesn't, we
	# still assume it refers to a bibliography entry.
	short_title = ref["target"].removeprefix("bib:")
	location = []
	for range in bibl.find("citedRange"):
		unit = range["unit"] or "page"
		if unit not in bibl_units:
			unit = "mixed"
		value = range.text()
		if not value:
			continue
		location.append((unit, value))
	return short_title, location

# For printing entries within the bibliography. In this context, bibl needs to
# be replaced with the bibliography entry.
@handler("listBibl/bibl")
def parse_listbibl_bibl(p, bibl):
	ref = bibl.first("ptr") or bibl.first("ref")
	if not ref or ref["target"].removeprefix("bib:") == "AuthorYear_01":
		return
	short_title, location = extract_bibl_ref(bibl, ref)
	if not short_title:
		return
	p.append(p.bib_entry(short_title, location=location))

bibl_rend_formats = ("default", "omitname", "ibid", "siglum")

# For printing bibliographic references.
@handler("bibl")
def parse_bibl_ref(p, bibl):
	rend = bibl["rend"]
	if rend not in bibl_rend_formats:
		rend = "default"
		assert rend in bibl_rend_formats
	# We use a dummy node if there is no ptr nor ref.
	ref = bibl.first("ptr") or bibl.first("ref") or tree.Tag("ref")
	short_title, location = extract_bibl_ref(bibl, ref)
	p.append(p.bib_reference(short_title, rend=rend, contents=list(ref),
		location=location))
	if (note := bibl.first("note")):
		p.dispatch(note)

@handler("ref")
@handler("ptr")
def parse_ref(p, ref):
	url = ref["target"]
	if not url:
		return p.dispatch_children(ref)
	url = urllib.parse.urlparse(url)
	# The fancy prefixes we use like "bib" and "part" are private URI
	# schemes.
	# See https://tei-c.org/release/doc/tei-p5-doc/en/html/SA.html#SAPU
	# However, we ignore what <listPrefixDef> says about the scheme. This
	# is hardcoded here.
	if url.scheme == "bib":
		return p.append(p.bib_reference(url.path, rend="siglum",
			contents=list(ref)))
	# Simplify the URL if it refers to something on our server:
	# http(s)?://(www\.)?dharmalekha.info/foo -> /foo
	if url.scheme in ("http", "https") and url.netloc in ("dharmalekha.info", "www.dharmalekha.info"):
		url = url._replace(scheme="", netloc="")
	if url.hostname:
		# It doesn't point to something on our server.
		url = url.geturl()
		p.push(tree.Tag("link", href=url))
		if ref.text():
			p.dispatch_children(ref)
		else:
			p.push(tree.Tag("span", class_="url"))
			p.append(url)
			p.join()
		return p.join()
	# We're dealing with a path ("foo", "/foo", etc.), thus something hosted
	# on our server. Make the path absolute and drop trailing slashes.
	# We have one of:
	# "foo" -> "/texts/foo"
	# "/texts/foo" -> "/texts/foo"
	# "/foo" -> "/foo"
	# "/foo/" -> "/foo"
	path = url.path.rstrip("/") or "/"
	path = posixpath.join("/texts", path)
	# If this is a text, drop the file extension, thus
	# "/texts/DHARMA_INSIDENKTuhanyaru.xml" -> "/texts/DHARMA_INSIDENKTuhanyaru"
	# And also remove the "DHARMA_" prefix:
	# "/texts/DHARMA_INSIDENKTuhanyaru" -> "/texts/INSIDENKTuhanyaru"
	if path.startswith("/texts/"):
		name = posixpath.basename(path)
		name = posixpath.splitext(name)[0]
		name = name.removeprefix("DHARMA_")
		path = posixpath.join(posixpath.dirname(path), name)
	url = url._replace(path=path).geturl()
	p.push(tree.Tag("link", href=url))
	if ref.text():
		p.dispatch_children(ref)
	elif path.startswith("/texts/"):
		p.push(tree.Tag("span", class_="text-id"))
		p.append(path.removeprefix("/texts/"))
		p.join()
	else:
		p.push(tree.Tag("span", class_="url"))
		p.append(path)
		p.join()
	p.join()

################################# Apparatus ###################################

def append_reading_sources(p, sources):
	refs = []
	for short_title in sources.split():
		short_title = short_title.removeprefix("bib:")
		if not short_title:
			continue
		common.append_unique(refs, short_title)
	for short_title in refs:
		p.append(" ")
		p.append(p.bib_reference(short_title, rend="siglum"))

@handler("lem")
def parse_lem(p, lem):
	p.push(tree.Tag("span", lang=lem.notes["assigned_lang"]))
	p.dispatch_children(lem)
	p.join()
	append_reading_sources(p, lem["source"])

@handler("rdg")
def parse_rdg(p, rdg):
	p.push(tree.Tag("span", class_="reading", tip="Reading", lang=rdg.notes["assigned_lang"]))
	p.dispatch_children(rdg)
	p.join()
	append_reading_sources(p, rdg["source"])

@handler("app")
def parse_app(p, app):
	if (n := app["loc"]):
		p.push(tree.Tag("span", class_="lb", tip="Line start"))
		p.append(f"⟨{n}⟩")
		p.join()
		p.append(" ")
	if (lem := app.first("lem")):
		p.dispatch(lem)
	rdgs = app.find("rdg")
	if rdgs:
		p.append(" \N{white medium diamond} ")
	notes = app.find("note") # we deal with other notes elsewhere
	for i, rdg in enumerate(rdgs):
		p.dispatch(rdg)
		if i < len(rdgs) - 1:
			p.append("; ")
		elif not notes:
			p.append(".")
	for note in notes:
		p.append(" • ")
		p.push(tree.Tag("span", lang=note.notes["assigned_lang"]))
		p.dispatch_children(note)
		p.join()

@handler("listApp")
def parse_listApp(p, listApp):
	apps = listApp.find("app[lem[not empty()]]")
	if not apps:
		return
	prev_loc = None
	for app in apps:
		if prev_loc == app["loc"]:
			p.append(" \N{EM DASH} ")
		else:
			if prev_loc is not None:
				p.join()
			p.push(tree.Tag("para"))
		p.dispatch(app)
		prev_loc = app["loc"]
	p.join()

################################# Editorial ####################################

@handler("num")
def parse_num(p, num):
	if num["value"] and num["value"] == num.text() and not num["cert"] == "low":
		tip = "" # Pointless to add a tooltip in this case.
	elif num["value"]:
		tip = f"Numeral {num['value']}"
	elif num["atLeast"] and num["atMost"]:
		tip = f"Numeral between {num['atLeast']} and {num['atMost']} inclusive"
	elif num["atLeast"]:
		tip = f"Numeral greater than or equal to {num['atLeast']}"
	elif num["atMost"]:
		tip = f"Numeral smaller than or equal to {num['atMost']}"
	elif num.text().isdigit() and not num["cert"] == "low":
		tip = "" # Pointless to add a tooltip in this case.
	else:
		tip = "Numeral"
	if num["cert"] == "low":
		tip += " (low certainty)"
	p.push(tree.Tag("span", class_="num", tip=tip or None))
	p.dispatch_children(num)
	p.join()

# Try to have more precise tooltips for this. If this does not work, we fall
# back to a generic one.
@handler("supplied[@reason='subaudible']")
def parse_supplied_subaudible(p, supplied):
	if not supplied.notes["assigned_lang"].is_source:
		tip = "Text added to the translation for the sake of target language syntax"
		return emit_supplied(p, supplied, tip, "[]")
	match supplied.text():
		case "'" | "’":
			tip = XML('<span class="italics">Avagraha</span> added by the editor to clarify the interpretation')
		case ".":
			tip = "Punctuation added by the editor at semantic break"
		case _:
			tip = "Editorial addition to clarify interpretation"
	return emit_supplied(p, supplied, tip, "⟨⟩")

# EGD "Additions to the translation"
# EGD "Marking up restored text"
# EGD "The basis of restoration"
supplied_tbl = {
	# EGD: "words added to the translation for the sake of target language
	# syntax"
	# subaudible is handled separately
	# EGD: "words implied by the context and added to the translation for
	# the sake of clarification or disambiguation"
	"explanation": ("()", "Text inserted into the translation as explanation or disambiguation"),
	# EGD: "lost" and "omitted" indicate "segments of translation corresponding
	# to text restored by the editor in the original" (they are used both
	# in the edition and in the translation)
	"lost": ("[]", "Lost text"),
	"omitted": ("⟨⟩", "Omitted text"),
	# EGD under "Marking up restored text" says that "undefined" is used when it's not possible
	# to tell whether we have "lost" or "omitted"
	"undefined": ("[]", "Text supplied for undefined reason (lost or omitted)")
}
# OK
@handler("supplied") # [not @reason='subaudible']
def parse_supplied(p, supplied):
	brackets, tip = supplied_tbl.get(supplied["reason"], supplied_tbl["lost"])
	return emit_supplied(p, supplied, tip, brackets)

def emit_supplied(p, supplied, tip, brackets):
	ldelim, rdelim = brackets
	p.push(tree.Tree())
	# XXX must omit <note> in all cases where we construct a tooltip
	p.append(copy.copy(tip))
	if supplied["cert"] == "low":
		p.append(" (low certainty)")
	match supplied["evidence"]:
		case "parallel":
			p.append("; restoration based on parallel")
		case "previouseditor":
			p.append("; restoration based on previous edition (not assessable)")
	tip = p.pop().xml()
	p.push(tree.Tag("span", class_="supplied", tip=tip))
	p.append_display(ldelim)
	p.dispatch_children(supplied)
	if supplied["cert"] == "low":
		p.append_display("?")
	p.append_display(rdelim)
	p.join()

# § Premodern insertion
add_place_tbl = {
	"inline": "Scribal addition within the same line or in the immediate vicinity of the locus",
	"below": "Scribal addition below the line",
	"above": "Scribal addition above the line",
	"top": "Scribal addition in the top margin",
	"bottom": "Scribal addition in the bottom margin",
	"left": "Scribal addition in the left margin",
	"right": "Scribal addition in the right margin",
	"overstrike": "Scribal addition made in the space where a previous string of text has been erased",
	"unspecified": "Scribal addition: no location information available",
}
@handler("add")
def parse_add(p, node, deleted=None):
	p.push(tree.Tree())
	tip = add_place_tbl.get(node["place"], add_place_tbl["unspecified"])
	p.append(tip)
	if deleted:
		p.append(" (overwritten text: ")
		p.push(tree.Tag("span", class_="del"))
		p.append("⟦")
		p.dispatch_children(deleted)
		p.append("⟧")
		p.join()
		p.append(")")
	tip = p.pop().xml()
	p.push(tree.Tag("span", class_="add", tip=tip))
	p.append_display("⟨⟨")
	p.dispatch_children(node)
	p.append_display("⟩⟩")
	p.join()

# § Premodern deletion
del_rend_tbl = {
	"strikeout": "Scribal deletion: text struck through or cross-hatched",
	"ui": XML('Scribal deletion: combined application of vowel markers <span class="italics">u</span> and <span class="italics">i</span> to characters to be deleted'),
	"other": "Scribal deletion",
	"corrected": "Scribal deletion: corrected text",
}
@handler("del")
def parse_del(p, node, added=None):
	p.push(tree.Tree())
	tip = del_rend_tbl.get(node["rend"], del_rend_tbl["other"])
	p.append(copy.copy(tip))
	if added:
		p.append(" (replacement text: ")
		p.push(tree.Tag("span", class_="add"))
		p.append("⟨⟨")
		p.dispatch_children(added)
		p.append("⟩⟩")
		p.join()
		p.append(")")
	tip = p.pop().xml()
	p.push(tree.Tag("span", class_="del", tip=tip))
	p.append_display("⟦")
	p.dispatch_children(node)
	p.append_display("⟧")
	p.join()

# § Premodern correction
@handler("subst")
def parse_subst(p, subst):
	# For search, should just keep the text of <add>
	add = subst.first("add")
	dele = subst.first("del")
	if not add or not dele:
		return p.dispatch_children(subst)
	parse_del(p, dele, add)
	parse_add(p, add, dele)

@handler("sic")
def parse_sic(p, sic, corr=None):
	p.push(tree.Tree())
	p.append("Incorrect text")
	if corr:
		p.append(" (emendation: ")
		p.push(tree.Tag("span", class_="corr"))
		p.append("⟨")
		p.dispatch_children(corr)
		p.append("⟩")
		p.join()
		p.append(")")
	p.push(tree.Tag("span", class_="sic", tip=p.pop().xml()))
	p.append_display("¿")
	p.dispatch_children(sic)
	p.append_display("?")
	p.join()

@handler("corr")
def parse_corr(p, corr, sic=None):
	p.push(tree.Tree())
	p.append("Emended text")
	if sic:
		p.append(" (original: ")
		p.push(tree.Tag("span", class_="sic"))
		p.append("¿")
		p.dispatch_children(sic)
		p.append("?")
		p.join()
		p.append(")")
	p.push(tree.Tag("span", class_="corr", tip=p.pop().xml()))
	p.append_display('⟨')
	p.dispatch_children(corr)
	p.append_display('⟩')
	p.join()

@handler("orig")
def parse_orig(p, orig, reg=None):
	p.push(tree.Tree())
	p.append("Non-standard text")
	if reg:
		p.append(" (standardisation: ")
		p.push(tree.Tag("span", class_="reg"))
		p.append("⟨")
		p.dispatch_children(reg)
		p.append("⟩")
		p.join()
		p.append(")")
	p.push(tree.Tag("span", class_="orig", tip=p.pop().xml()))
	p.append_display("¡")
	p.dispatch_children(orig)
	p.append_display("!")
	p.join()

@handler("reg")
def parse_reg(p, reg, orig=None):
	p.push(tree.Tree())
	p.append("Standardised text")
	if orig:
		p.append(" (original: ")
		p.push(tree.Tag("span", class_="orig"))
		p.append_display("¡")
		p.dispatch_children(orig)
		p.append_display("!")
		p.join()
		p.append(")")
	p.push(tree.Tag("span", class_="reg", tip=p.pop().xml()))
	p.append_display("⟨")
	p.dispatch_children(reg)
	p.append_display("⟩")
	p.join()

@handler("unclear")
def parse_unclear(p, node, standalone=True):
	p.push(tree.Tree())
	if node["cert"] == "low":
		p.append("Tentative reading")
	else:
		p.append("Unclear text")
	if node["reason"] == "eccentric_ductus":
		p.append(" (")
		p.push(tree.Tag("span", class_="italics"))
		p.append("eccentric_ductus")
		p.join()
		p.append(")")
	p.push(tree.Tag("span", class_="unclear", tip=p.pop().xml()))
	if standalone:
		p.append_display("(")
	p.dispatch_children(node)
	if node["cert"] == "low":
		p.append_display("?")
	if standalone:
		p.append_display(")")
	p.join()

@handler("choice")
def parse_choice(p, node):
	"""We expect one of the following:

	#1 <choice>(<unclear>...</unclear>)+</choice>
	#2 <choice><sic>...</sic><corr>...</corr></choice>
	#3 <choice><orig>...</orig><reg>...</reg></choice>

	And we need to generate:

	#2

	#3 <views>
		<physical>orig</physical>
		<logical>reg</logical>
		<full>
			<split>
				<display>orig reg</display>
				<search>reg</search>
			</split>
		</full>
	</views>
	"""
	children = node.find("*")
	if all(child.name == "unclear" for child in children):
		make_multiple_unclear(p, children)
	elif len(children) != 2:
		p.dispatch_children(node)
	elif (sic := node.first("sic")) and (corr := node.first("corr")):
		p.push(tree.Tree())
		parse_sic(p, sic, corr)
		one = p.pop()
		p.push(tree.Tree())
		parse_corr(p, corr, sic)
		two = p.pop()
		make_choice_pair(p, one, two)
	elif (orig := node.first("orig")) and (reg := node.first("reg")):
		p.push(tree.Tree())
		parse_orig(p, orig, reg)
		one = p.pop()
		p.push(tree.Tree())
		parse_reg(p, reg, orig)
		two = p.pop()
		make_choice_pair(p, one, two)
	else:
		p.dispatch_children(node)

def make_multiple_unclear(p, nodes: list[tree.Node]):
	"""Output:

	<split>
		<display>unclear1 unclear2</display>
		<search>unclear1</search>
	</split>
	"""
	p.push(tree.Tag("split"))
	p.push(tree.Tag("display"))
	p.push(tree.Tag("span", tip="Unclear (several possible readings)"))
	p.append("(")
	for i, node in enumerate(nodes):
		p.dispatch_children(node)
		if i < len(nodes) - 1:
			p.append("/")
	p.append(")")
	p.join()
	p.join("display")
	p.push(tree.Tag("search"))
	p.dispatch_children(nodes[0])
	p.join()
	p.join("split")

def make_choice_pair(p, one, two):
	"""
	<views>
		<physical>one</physical>
		<logical>two</logical>
		<full>
			<split>
				<display>one two</display>
				<search>two</search>
			</split>
		</full>
	</views>
	"""
	# Three views
	p.push(tree.Tag("views"))
	# Physical
	p.push("physical")
	p.append(one)
	p.join("physical")
	# Logical
	p.push("logical")
	p.append(two)
	p.join("logical")
	# Full
	p.push("full")
	p.push("split")
	p.push("display")
	p.append(one)
	p.append(two)
	p.join("display")
	p.push("search")
	p.append(two)
	p.join()
	p.join()
	p.join("full")
	p.join("views")

# EGD "Editorial deletion (suppression)"
@handler("surplus")
def parse_surplus(p, node):
	p.push(tree.Tag("span", class_="surplus", tip="Superfluous text erroneously added by the scribe"))
	p.append_display("{")
	p.dispatch_children(node)
	p.append_display("}")
	p.join()

# > editorial

# For <note> elements anywhere but in the apparatus, where <note> has a peculiar
# purpose.
# XXX handle nested notes here, or fix them afterwards? fix them afterwards
@handler("note")
def parse_note(p, note):
	out = p.push(tree.Tag("note", lang=note.notes["assigned_lang"]))
	if (resps := note["resp"]):
		append_names(p, resps.split())
		p.append(": ")
	elif (refs := note["source"]):
		append_sources(p, refs.split())
		p.append(": ")
	p.dispatch_children(note)
	p.join()
	p.document.notes.append(out)

# Put <foreign> in italics, unless @rend="roman"
@handler("foreign")
def parse_foreign(p, foreign):
	class_ = "italics"
	for word in foreign["rend"].lower().split():
		match word:
			case "italic" | "italics":
				class_ = "italics"
			case "roman":
				class_ = "roman"
	p.push(tree.Tag("span", class_=class_, lang=foreign.notes["assigned_lang"]))
	p.dispatch_children(foreign)
	p.join()

################################# Milestones ###################################

def get_n(node):
	n = node["n"]
	if not n:
		return ""
	n = n.replace("_", " ").replace("-", "\N{en dash}")
	return n

def milestone_break(node):
	return common.to_boolean(node["break"], True)

def append_milestone_label(p, node, unit):
	span = tree.Tag("span", tip=f"{unit.title()} start")
	p.push(span)
	p.append("⟨")
	if unit == "line":
		if (n := get_n(node)):
			p.append(n)
		else:
			p.append("Line")
	else:
		p.append(unit.title())
		if (n := get_n(node)):
			p.append(" ")
			p.append(n)
	# If a <label> follows immediately, associate it with the milestone.
	# But not if this <label> is a list element, because in this case it
	# has a different meaning.
	if (label := node.first("stuck-following-sibling::label[not parent::list]")):
		p.append(": ")
		p.push(tree.Tag("span", lang=label.notes["assigned_lang"]))
		p.dispatch_children(label)
		p.join()
		p.visited.add(label)
	p.append("⟩")
	p.join()

@handler("milestone")
def parse_milestone(p, node):
	break_ = milestone_break(node)
	match node["type"]:
		case "pagelike":
			type = "npage"
		case "gridlike" | _:
			type = "ncell"
	p.push(tree.Tag(type, break_=common.from_boolean(break_)))
	append_milestone_label(p, node, node["unit"] or "column")
	if node["type"] == "pagelike":
		append_fws(p, node)
	p.join()

@handler("lb")
def parse_lb(p, node):
	break_ = milestone_break(node)
	p.push(tree.Tag("nline", break_=common.from_boolean(break_)))
	append_milestone_label(p, node, "line")
	p.join()

# <fw> is for pagelike milestones only.
# See https://www.tei-c.org/release/doc/tei-p5-doc/en/html/PH.html#PHSK
fw_places = {
	"bot-left": "bottom left",
	"bot-right": "bottom right",
	"bottom": "bottom",
	"left": "left",
	"right": "right",
	"top": "top",
	"top-left": "top left",
	"top-right": "top right",
}
@handler("fw")
def parse_fw(p, fw):
	p.push(tree.Tag("span", class_="fw", tip="Foliation"))
	# XXX need different formatting for phys/log/full
	p.append("⟨")
	if (place := fw["place"]):
		# If the value is not in our table, keep it, even
		# though it's wrong.
		place = fw_places.get(place, place)
	else:
		place = "top"
	p.append(place)
	if not fw.empty:
		p.append(": ")
		p.push(tree.Tag("span", class_="fw-contents"))
		p.dispatch_children(fw)
		p.join()
	p.append("⟩")
	p.join()

def append_fws(p, pb):
	node = pb.first("stuck-following-sibling::label") or pb
	while (fw := node.first("stuck-following-sibling::fw")):
		p.dispatch(fw)
		p.visited.add(fw)
		node = fw

@handler("pb")
def parse_pb(p, node):
	break_ = milestone_break(node)
	p.push(tree.Tag("npage", break_=common.from_boolean(break_)))
	append_milestone_label(p, node, "page")
	append_fws(p, node)
	p.join()

# > milestones

# Valid cases are:
#	<space [type="semantic"]/> (shorthand is '_')
#	<space [type="semantic"] quantity=... unit="character"/>
#	<space type="vacat" quantity=... unit="character"/>
#	<space type="(binding-hole|descender|ascender|defect|feature)"/>
#	<space type="unclassified"/>
#	<space type="unclassified" quantity=... unit="character"/>
space_types = {
	"semantic": {
		"text": "_",
		"tip": "semantic space",
	},
	"binding-hole": {
		"text": "◯",
		"tip": "binding hole",
	},
	"descender": {
		"text": "⊔",
		"tip": "space left blank in a line because (part of) another character hanging down from the previous line encroaches on the current line",
	},
	"ascender": {
		"text": "⊓",
		"tip": "space left blank in a line because (part of) another (pre-conceived) character popping up from the following line encroaches on the current line",
	},
	"defect": {
		"text": "□",
		"tip": "space; the writing skips a blemish of the surface that was not deliberately created (such as a natural crack or pit, or a fault in the creation of the writing surface)",
	},
	"feature": {
		"text": "_",
		"tip": "space; the writing skips a deliberately created feature (other than binding holes, ascenders and descenders) on the surface (such as engraved artwork, high relief, or a seal attached directly to a copper plate)",
	},
	"vacat": {
		"text": "_",
		"tip": "vacat space; the area was left blank when the rest of the inscription was engraved, possibly with the intent to be filled later on",
	},
	"unclassified": {
		"text": "_",
		"tip": "significant space that does not fit other categories",
	}
}
@handler("space")
def parse_space(p, space):
	type = space["type"]
	if type not in space_types:
		type = "semantic"
	quant = 0
	unit = ""
	if type in ("semantic", "vacat", "unclassified"):
		quant = space["quantity"]
		if not quant.isdigit():
			quant = "1"
		quant = int(quant)
		if quant < 1:
			quant = 1
		unit = space["unit"]
		if unit != "character":
			unit = "character"
	info = space_types[type]
	tip = info["tip"]
	text = info["text"]
	if type in ("semantic", "vacat", "unclassified"):
		if quant < 2:
			tip = f"small {type} space (from barely noticeable to less than two average character widths in extent)"
		else:
			tip = f"large {type} space (about {quant} {unit}s wide)"
		text *= quant
	p.push(tree.Tag("span", class_="space", tip=common.sentence_case(tip)))
	p.append(text) # XXX must only be made visible in physical and full, not in logical
	p.join()

# <abbreviations

@handler("abbr")
def parse_abbr(p, node):
	p.push(tree.Tag("span", class_="abbr", tip="Abbreviated text"))
	p.dispatch_children(node)
	p.join()

@handler("ex")
def parse_ex(p, node):
	if node["cert"] == "low":
		tip = "Abbreviation expansion (uncertain)"
	else:
		tip = "Abbreviation expansion"
	p.push(tree.Tag("span", class_="abbr-expansion", tip=tip))
	p.append_display("(")
	p.dispatch_children(node)
	p.append_display(")")
	p.join()

@handler("am")
def parse_am(p, am):
	p.push(tree.Tag("span", class_="abbr-mark", tip="Abbreviation mark"))
	p.dispatch_children(am)
	p.join()

# We expect:
#	<expan>((<abbr>(text|<am>...</am>)</abbr>)|(<ex>...</ex>))+</expan>
# XXX This is not good (can't deal with <note>, etc.). Need to straighten this out.
@handler("expan")
def parse_expan(p, node):
	def iter_abbr_without_am(cur):
		match cur:
			case tree.Tag("am"):
				pass
			case tree.Tag():
				for child in cur:
					yield from iter_abbr_without_am(child)
			case tree.String():
				yield cur
	p.push(tree.Tree())
	p.append("Abbreviation (contracted form: ")
	p.push(tree.Tag("span", class_="abbr-contracted"))
	for abbr in node.find("abbr"):
		p.append(abbr.text())
	p.join()
	p.append("; expanded form: ")
	p.push(tree.Tag("span", class_="abbr-expanded"))
	for child in node.find("*[name() = 'abbr' or name() = 'ex']"):
		if child.name == "ex":
			p.append(child.text())
			continue
		for s in iter_abbr_without_am(child):
			p.append(s.copy())
	p.join()
	p.append(")")
	p.push(tree.Tag("span", class_="abbr-full", tip=p.pop().xml()))
	p.dispatch_children(node)
	p.join()

# >abbreviations

@handler("seg[stuck-child::gap]")
def parse_other_seg(p, seg):
	# We expect something like:
	# <seg met="+++-++"><gap reason="lost" quantity="6" unit="character"/></seg>
	# In this case, use the same tooltip we would use for <gap>, but display
	# the meter instead of ****, etc.
	# XXX what about search? For now let's just convert prosodic pattern
	met = seg["met"]
	if not met:
		return parse_seg(p, seg)
	if prosody.is_pattern(met):
		met = prosody.render_pattern(met)
	elif (entry := p.get_prosody_entry(met)):
		met, _, _ = entry
	else:
		return parse_seg(p, seg)
	p.push(tree.Tag("span", lang=seg.notes["assigned_lang"]))
	_, _, tip = parse_gap(p, seg.first("stuck-child::gap"))
	if tip:
		p.top["tip"] = tip
	p.append_display("[")
	p.append(met)
	p.append_display("]")
	p.join()

# There is @type=aksara|component which we are not dealing with but that is
# apparently useless.
@handler("seg") # seg[not stuck-child::gap]
def parse_seg(p, seg):
	p.push(tree.Tag("span", lang=seg.notes["assigned_lang"]))
	rend = seg["rend"].split()
	if "pun" in rend:
		p.push(tree.Tag("span", class_="pun", tip=XML('Pun (<span class="italics">ślesa</span>').xml()))
		p.append_display("{")
	if "check" in rend:
		p.push(tree.Tag("span", class_="check", tip="To be checked"))
	if seg["cert"] == "low":
		p.push(tree.Tag("span", tip="Uncertain segment"))
		p.append_display("¿")
	p.dispatch_children(seg)
	if seg["cert"] == "low":
		p.append_display("?")
		p.join()
	if "check" in rend:
		p.join()
	if "pun" in rend:
		p.append_display("}")
		p.join()
	p.join()

# XXX TODO for gaps, the search representation should be a sequence of some
# special placeholder character (if @unit='character')

# XXX not general enough; might be better to take into account the langguage instead
@handler("div[@type='translation']//gap[@reason='ellipsis']")
def handle_gap_ellipsis(p, gap):
	p.push(tree.Tag("span", tip="Untranslated segment"))
	p.append("\N{horizontal ellipsis}")
	p.join()

def parse_gap(p, gap) -> tuple[str, str, str]:
	reason = gap["reason"] or "undefined" # most generic choice
	quantity = gap["quantity"]
	precision = gap["precision"]
	unit = gap["unit"] or "character"
	if reason == "ellipsis":
		repl = "\N{horizontal ellipsis}"
		return repl, repl, ""
	if reason == "undefined":
		reason = "lost or illegible"
	if gap.first("stuck-child::certainty[@match='..' and @locus='name']"):
		reason = f"possibly {reason}"
	if unit == "component":
		unit = "character component"
	phys_repl = None
	if quantity.isdigit():
		quantity = int(quantity)
		repl = "["
		if precision == "low":
			repl += "ca. "
		if unit == "character":
			if reason == "lost":
				repl += f"{quantity}+"
			elif reason == "illegible":
				repl += f"{quantity}×"
			else:
				# reason = "undefined" (lost or illegible)
				repl += f"{quantity}*"
		elif unit == "character component":
			repl += quantity * "."
		else:
			repl += "%d %s %s" % (quantity, reason, common.numberize(unit, quantity))
		repl += "]"
		phys_repl = "["
		if precision == "low" and unit != "character":
			phys_repl += "ca. "
		if unit == "character":
			phys_repl += quantity * "*"
		elif unit == "character component":
			phys_repl += quantity * "."
		else:
			phys_repl += "%d %s %s" % (quantity, reason, common.numberize(unit, quantity))
		phys_repl += "]"
		tip = ""
		if precision == "low":
			tip += "About "
		tip += "%d %s %s" % (quantity, reason, common.numberize(unit, quantity))
	else:
		if unit == "character":
			repl = "[…]"
		else:
			repl = "[unknown number of %s %s]" % (reason, common.numberize(unit, +333))
		tip = "Unknown number of %s %s" % (reason, common.numberize(unit, +333))
	return phys_repl or repl, repl, tip

# XXX not refactored
# @unit="component" is for character components like vowel markers, etc.
# @unit="character" is for akṣaras
# EGD: The EpiDoc element <gap/> ff (full section 5.4)
# EGD: "Scribal Omission without Editorial Restoration"
@handler("gap")
def handle_gap(p, gap):
	phys_repl, log_repl, tip = parse_gap(p, gap)
	assert not isinstance(log_repl, tree.Node)
	p.push(tree.Tag("views"))
	for display, node in (("physical", phys_repl), ("logical", log_repl),
		("full", log_repl)):
		p.push(tree.Tag(display, lang=gap.notes["assigned_lang"]))
		if tip:
			p.push(tree.Tag("span", tip=tip))
			p.append(node)
			p.join()
		else:
			p.append(node)
		p.join()
	p.join()

"""
The following table was produced with this code:

import requests, csv, io, re

NAME_COLUMN = 1
DECOMP_COLUMN = 5

r = requests.get("https://www.unicode.org/Public/UCD/latest/ucd/UnicodeData.txt")
rows = csv.reader(io.StringIO(r.text), delimiter=";")
tbl = {}
for row in rows:
        m = re.fullmatch(r"<fraction> ([0-9A-Fa-f]+) 2044 ([0-9A-Fa-f]+)", row[DECOMP_COLUMN])
        if not m:
                continue
        name = row[NAME_COLUMN]
        num, den = m.group(1), m.group(2)
        num, den = int(num, 16), int(den, 16)
        num, den = chr(num), @)
        tbl[name] = (num, den)

rev = {}
for k, v in tbl.items():
        assert not v in rev
        rev[v] = k

for k, v in sorted(rev.items()):
        print('(%s, %s): "\\N{%s}",' % (k[0], k[1], v.lower()))
"""
composed_fractions = {
	(0, 3): "\N{vulgar fraction zero thirds}",
	(1, 2): "\N{vulgar fraction one half}",
	(1, 3): "\N{vulgar fraction one third}",
	(1, 4): "\N{vulgar fraction one quarter}",
	(1, 5): "\N{vulgar fraction one fifth}",
	(1, 6): "\N{vulgar fraction one sixth}",
	(1, 7): "\N{vulgar fraction one seventh}",
	(1, 8): "\N{vulgar fraction one eighth}",
	(1, 9): "\N{vulgar fraction one ninth}",
	(2, 3): "\N{vulgar fraction two thirds}",
	(2, 5): "\N{vulgar fraction two fifths}",
	(3, 4): "\N{vulgar fraction three quarters}",
	(3, 5): "\N{vulgar fraction three fifths}",
	(3, 8): "\N{vulgar fraction three eighths}",
	(4, 5): "\N{vulgar fraction four fifths}",
	(5, 6): "\N{vulgar fraction five sixths}",
	(5, 8): "\N{vulgar fraction five eighths}",
	(7, 8): "\N{vulgar fraction seven eighths}",
}
# We try to use a uniform representation for fractions. If there is a
# precomposed code point for the given fraction, we use it, otherwise we use
# <sup>9</sup> + fraction slash + <sub>8</sub>.
@handler("g[@type='numeral']")
def parse_g_numeral(p, node):
	frac = re.match("([0-9]+)[/\N{fraction slash}]([0-9]+)", node.text())
	if frac:
		num, den = int(frac.group(1)), int(frac.group(2))
		composed = composed_fractions.get((num, den))
		if composed:
			p.append(composed)
		else:
			sup = tree.Tag("span", class_="sup")
			sup.append(str(num))
			p.append(sup)
			p.append("\N{fraction slash}")
			sub = tree.Tag("span", class_="sub")
			sub.append(str(den))
			p.append(sub)
	else:
		p.dispatch_children(node)

# g[not @type='numeral']
@handler("g")
def parse_g(p, node):
	# <g type="...">\.</g> for punctuation marks
	# <g type="...">§+</g> for space fillers
	# <g type="..."></g> in the other cases viz. for symbols whose function
	# is unclear.
	text = node.text()
	info = gaiji.get(node["type"])
	if text == ".":
		tip = f"Punctuation symbol: {info['description']}"
	elif re.fullmatch("§+", text):
		tip = f"Space-filler symbol: {info['description']}"
	else:
		tip = f"Symbol: {info['description']}"
	p.push(tree.Tag("split"))
	p.push(tree.Tag("display"))
	sym = tree.Tag("span", tip=tip)
	if info["text"]:
		sym["class"] = "symbol"
		sym.append(info["text"])
	else:
		sym["class"] = "symbol-placeholder"
		sym.append(f"<{info['name']}>") # should not include that in search
	p.append(sym)
	p.join()
	p.push(tree.Tag("search"))
	p.append(info["search"] or "�")
	p.join()
	p.join("split")

hi_table = {
	"italic": tree.Tag("span", class_="italics"),
	"bold": tree.Tag("span", class_="bold"),
	"superscript": tree.Tag("span", class_="sup"),
	"subscript": tree.Tag("span", class_="sub"),
	"check": tree.Tag("span", class_="check"),
	"grantha": tree.Tag("span", class_="grantha", tip="Grantha text"),
}
@handler("hi")
def parse_hi(p, hi):
	n = 0
	for rend in common.unique(hi["rend"].split()):
		node = hi_table.get(rend)
		if node:
			p.push(node.copy())
			n += 1
	p.dispatch_children(hi)
	for _ in range(n):
		p.join()

# < para-like

def make_meter_heading(p, met):
	if not met:
		return
	if prosody.is_pattern(met):
		return prosody.render_pattern(met)
	if met in ("mixed", "uncertain"):
		ret = tree.Tag("span")
		ret.append(common.sentence_case(met) + " meter")
		return ret
	if met == "free":
		ret = tree.Tag("span")
		ret.append("Free verse")
		return ret
	entry = p.get_prosody_entry(met)
	if not entry:
		ret = tree.Tag("span")
		ret.append(common.sentence_case(met))
		return ret
	pattern, description, entry_id = entry
	name = common.sentence_case(met)
	if pattern:
		value = pattern.xml()
	elif description:
		value = description
	else:
		value = "No metre description available"
	p.push(tree.Tag("link", href=f"/prosody#prosody-{entry_id}"))
	p.push(tree.Tag("span", tip=value))
	p.append(name)
	p.join()
	return p.pop()

@handler("lg")
@handler("p[@rend='stanza']")
@handler("ab[@rend='stanza']")
def parse_lg(p, lg):
	"""The guide does not talk about ab[@rend='stanza'], but we still try
	to process it if it appears in an edition.
	"""
	p.push(tree.Tag("verse", lang=lg.notes["assigned_lang"]))
	# Generally we have a single number e.g. "10", but sometimes ranges
	# e.g. "10-20" (with various types of dashes).
	n = get_n(lg)
	unsure = False
	if (tmp := lg.first("stuck-child::certainty[@match='../@met' and @locus='value']")):
		p.visited.add(tmp)
		unsure = True
	met = make_meter_heading(p, lg["met"])
	if n or met:
		p.push(tree.Tag("head"))
		if n and met:
			p.append(n)
			p.append(". ")
			p.append(met)
			if unsure:
				p.append("(?)")
		elif n:
			p.append(n)
			p.append(".")
		else:
			assert met
			p.append(met)
			if unsure:
				p.append("(?)")
		p.join()
	# Ensure that we always have at least one verse-line. Note that people
	# do use <l> within <p rend="stanza"> in the traduction, so we do it
	# even for <p>, not just <lg>.
	if not lg.first("l"):
		p.push(tree.Tag("verse-line"))
		p.dispatch_children(lg)
		p.join()
	else:
		p.dispatch_children(lg)
		# Deal with l/@enjamb: <l>foo</l> <l>bar</l> means that the text
		# is "foo bar", while <l enjamb="yes">foo</l> <l>bar</l> means
		# that the text is "foobar". We convert this @enjamb to a @break
		# attribute on verse-line: verse-line[@break='no'] means that
		# there is no break between the current verse-line and the
		# preceding one; while verse-line[@break='yes'] means that a
		# space should be inserted at the beginning of the current
		# verse-line while converting the text to the physical display
		# mode.
		olds = lg.find("l")
		news = p.top.find("verse-line")
		assert len(olds) == len(news)
		for i, new in enumerate(news):
			if i == 0 or not common.to_boolean(olds[i - 1]["enjamb"], False):
				new["break"] = "true"
			else:
				new["break"] = "false"
	p.join()

# As far as we're concerned, <ab> is just a <p>, so we treat them identically.
# We deal with stanzas in another handler.
@handler("ab")
@handler("p")
def parse_p(p, para):
	# If the para contains <l> elements, most likely the user forgot to add
	# @rend='stanza'. <l> elements should only appear within a stanza. Thus
	# we assume the user meant @rend='stanza' and parse the paragraph as a
	# verse.
	if para.first("l"):
		return parse_lg(p, para)
	p.push(tree.Tag("para", lang=para.notes["assigned_lang"]))
	if (n := get_n(para)):
		# See e.g. http://localhost:8023/display/DHARMA_INSSII0400223
		# Should be displayed like <lb/> is in the edition.
		p.push(tree.Tag("span", class_="lb", tip="Line start"))
		p.append(f"⟨{n}⟩")
		p.join()
		p.append(" ")
	p.dispatch_children(para)
	p.join()

def append_meter_description(p, met):
	if prosody.is_pattern(met):
		p.append(prosody.render_pattern(met))
	elif (entry := p.get_prosody_entry(met)):
		pattern, _, _ = entry
		p.append(met)
		p.append(" (")
		p.append(pattern)
		p.append(")")
	else:
		p.append(met)

@handler("l")
def parse_l(p, l):
	p.push(tree.Tree())
	if (real := l["real"]):
		p.append("Irregular meter: ")
		append_meter_description(p, real)
		if (met := l["met"]):
			p.append("; based on ")
			append_meter_description(p, met)
	elif (met := l["met"]):
		p.append("Meter: ")
		append_meter_description(p, met)
	p.push(tree.Tag("verse-line", n=get_n(l), tip=p.pop().xml()))
	p.dispatch_children(l)
	p.join()

# > para-like

# < lists

"""
XXX special type for manu?

INSII2400053

réduire les espaces entre ce qui précède et suit du para + entre les items
(pas paragraphe "purs", mais sauts de lignes).

<p><list><item>...</list></p>

<p>bla bla bla <list><item>...</item></list> bla bla bla</p>

<p>bla bla bla <list><item>...</item></list></p>

<p><list><item>...</item></list> bla bla bla</p>
"""

# In HTML, we cannot have <p><ul>...</ul></p>, the <ul> or <ol> must be outside
# of <p>, so we need to generate a compatible representation. OTOH, HTML allows
# <dl> within <p>, so no special treatment is needed in this case. Still, it
# might be better to use the same structure for both.

@handler("list[@rend='description' or label]")
def parse_description_list(p, lst):
	p.push(tree.Tag("dlist"))
	# We expect a series of (label, item). Only these elements are supposed
	# to occur within a list. But still try to deal with other elements.
	# In particular, people might be tempted to insert milestones between
	# list items.
	last = "item"
	for thing in lst.find("*"):
		assert isinstance(thing, tree.Tag)
		if thing.name not in ("label", "item"):
			p.dispatch(thing)
			continue
		match thing.name:
			case "label":
				if last == "label":
					p.append(tree.Tag("value"))
				p.push(tree.Tag("key"))
				p.dispatch_children(thing)
				p.join()
			case "item":
				if last == "item":
					p.append(tree.Tag("key"))
				p.push(tree.Tag("value"))
				p.dispatch_children(thing)
				p.join()
		last = thing.name
	if last == "label":
		p.append(tree.Tag("value"))
	p.join("dlist")

@handler("list")
def parse_list(p, lst):
	rend = lst["rend"]
	if rend not in ("plain", "bulleted", "numbered"):
		rend = "plain"
	p.push(tree.Tag("elist", type=rend))
	for thing in lst.find("*"):
		assert isinstance(thing, tree.Tag)
		if thing.name not in ("label", "item"):
			p.dispatch(thing)
			continue
		p.push(tree.Tag("item"))
		p.dispatch_children(thing)
		p.join()
	p.join()

# > lists

# I really don't like the encoding we use for <listBibl>, because there is no
# reason why a <ptr> should produce something other than a link. But we're
# stuck with that. Apparently, this was borrowed from epiDoc, see:
# https://epidoc.stoa.org/gl/latest/supp-bibliography.html
# Still doesn't make it a good idea.
@handler("listBibl")
def parse_listBibl(p, node):
	# We expect @type to be one of "primary" or "secondary", but
	# still accept other values. In the latter case, we just put the @type
	# in capitals, so it kinda works with custom values.
	p.push(tree.Tag("div"))
	if (type := node["type"]):
		p.push(tree.Tag("head", lang="study_other latin"))
		p.append(common.sentence_case(type))
		p.join()
	p.dispatch_children(node)
	p.join()

# Title of the edited text (in the teiHeader).
@handler("titleStmt/title")
def parse_title_in_header(p, title):
	p.dispatch_children(title)

# Titles within the document body (per contrast with the title of the edition).
# EGD 10.4.2. Encoding titles.
@handler("title")
def parse_title(p, title):
	p.push(tree.Tag("span", tip="Work title"))
	if title["level"] == "a":
		p.append("“")
		p.dispatch_children(title)
		p.append("”")
	elif title["rend"] == "plain":
		p.dispatch_children(title)
	else:
		p.push(tree.Tag("span", class_="title"))
		p.dispatch_children(title)
		p.join()
	p.join()

@handler("q")
@handler("quote")
def parse_quote(p, q):
	if q["rend"] == "block":
		p.push(tree.Tag("quote", lang=q.notes["assigned_lang"]))
		# XXX <quote> cannot appear within a <p> in HTML!
		# and idem for <cit> below.
		# https://html.spec.whatwg.org/#elements-3
		p.dispatch_children(q)
		p.join()
	else:
		p.append("“")
		# XXX should fix up space here
		p.push(tree.Tag("span", lang=q.notes["assigned_lang"]))
		p.dispatch_children(q)
		p.join()
		p.append("”")

@handler("cit")
def parse_cit(p, cit):
	# <cit>
	#    <quote>the text</quote>
	#    <bibl><ptr target="bib:Agrawala1983_01"/></bibl>
	# </cit>
	#
	# "the text" (Agrawala 1983)
	q = cit.first("*[name() = 'q' or name() = 'quote']")
	bibl = cit.first("bibl")
	if not bibl and not q:
		return
	if not bibl:
		return p.dispatch_children(q)
	if not q:
		return p.dispatch_children(bibl)
	if q["rend"] == "block":
		p.push(tree.Tag("quote", lang=q.notes["assigned_lang"]))
		p.push(tree.Tag("source", lang="study_other latin"))
		p.dispatch(bibl)
		p.join()
		p.dispatch_children(q)
		p.join()
	else:
		p.append("“")
		p.push(tree.Tag("span", lang=q.notes["assigned_lang"]))
		p.dispatch_children(q)
		p.join()
		p.append("”")
		p.append(" (")
		p.dispatch(bibl)
		p.append(")")

def append_unique_name(items, ident, name):
	for i, (cand_ident, cand_name) in enumerate(items):
		if ident is None:
			if cand_name == name:
				return
		elif cand_ident is None:
			if cand_name == name:
				items[i] = (ident, name)
				return
		elif cand_ident == ident or cand_name == name:
			return
	items.append((ident, name))

# We don't attempty to preserve the structure <forename>+<surname> for
# searching, because we can also have just <name>, so it's simpler to use
# a simple string.
def gather_people(stmt, *paths):
	nodes = [node for path in paths for node in stmt.find(path)]
	# Sort by order of appearance in the file
	nodes.sort(key=lambda node: node.location.start)
	ret = []
	for node in nodes:
		ident = node["ref"].removeprefix("part:")
		if ident == "jodo":
			# John Doe, placeholder. Alternatively, we could keep it
			# only if no author is given (we're already doing that
			# for languages, with "und").
			continue
		# Use the name given in the contributors list instead of the one
		# given in this XML file. If the id is invalid or not given,
		# however, use the name given in the XML file.
		name = people.plain(ident)
		if name:
			append_unique_name(ret, ident, name)
			continue
		# We should have either <forename>+<surname> or just <name>. But
		# also prepare for <surname>+<forename> or a plain string.
		first, last = node.first("forename"), node.first("surname")
		if first and last:
			name = first.text(space="preserve") + " " + last.text(space="preserve")
		else:
			name = node.text(space="preserve")
		name = common.normalize_space(name)
		if not name:
			continue
		append_unique_name(ret, None, name)
	return ret

# We only expect this to appear at /TEI/teiHeader/fileDesc/titleStmt (and a
# single occurrence).
@handler("titleStmt")
def parse_titleStmt(p, stmt):
	# Text title.
	# We should only have a single <title> elements, but, if there are many,
	# join them into a single string.
	# The EGD prescribes to only use a plain string within <title>, but we
	# relax this rule and allow tags here. See e.g. DHARMA_INSPallava00506.
	for title in stmt.find("title"):
		p.push(tree.Tree())
		p.dispatch(title)
		p.document.title.append(p.pop())
	# Author of the text (only for critical editions).
	p.document.authors = gather_people(stmt, "author")
	# Editor(s) of the text.
	# The only allowed form is respStmt/persName, but also prepare for a few
	# other forms that are valid TEI but not valid DHARMA.
	p.document.editors = gather_people(stmt, "respStmt/persName", "editor", "principal", "respStmt/name")

@handler("roleName")
@handler("measure")
@handler("date")
@handler("placeName")
@handler("persName")
@handler("text")
@handler("term")
@handler("gloss")
def parse_just_dispatch_all(p, node):
	p.dispatch_children(node)

@handler("TEI") # /TEI
@handler("teiHeader") # /TEI/teiHeader
@handler("fileDesc") # /TEI/teiHeader/fileDesc
@handler("sourceDesc") # /TEI/teiHeader/fileDesc/sourceDesc
@handler("msDesc") # /TEI/teiHeader/fileDesc/sourceDesc/msDesc
@handler("msContents") # /TEI/teiHeader/fileDesc/sourceDesc/msDesc/msContents
@handler("text") # /TEI/text
@handler("body") # /TEI/text/body
@handler("physDesc")
def parse_just_dispatch(p, node):
	p.dispatch_children(node)

# These elements and their children should be ignored.
@handler("editionStmt")
@handler("facsimile") # for images, will see later on
@handler("handShift")
@handler("publicationStmt") # /TEI/teiHeader/fileDesc/publicationStmt
@handler("msIdentifier") # /TEI/teiHeader/fileDesc/sourceDesc/msDesc/msIdentifier
@handler("encodingDesc") # /TEI/teiHeader/encodingDesc
@handler("revisionDesc") # /TEI/teiHeader/revisionDesc
def parse_ignore(p, node):
	pass

# We expect a single occurrence at
# /TEI/teiHeader/fileDesc/sourceDesc/msDesc/physDesc/handDesc
@handler("handDesc")
def parse_handDesc(p, desc):
	# TODO the guide should really disallow summary and just allow a
	# sequence of paragraphs.
	root = desc.first("summary") or desc
	p.push(tree.Tree())
	p.dispatch_children(root)
	p.document.hand = p.pop()

# We expect a single occurrence at
# /TEI/teiHeader/fileDesc/sourceDesc/msDesc/msContents/summary
@handler("summary")
def parse_contents_summary(p, summ):
	# We're supposed to have either a series of <p>, or a piece of text
	# without divisions. If we have no <p>, create one and wrap the
	# whole contents into it.
	p.push(tree.Tree())
	p.dispatch_children(summ)
	p.document.summary = p.pop()

def fetch_resp(resp):
	resp = people.plain(resp.removeprefix("part:")) or resp
	return html.escape(resp)

# We must process the bibliography in two steps. First, collect bibliography
# entries in div[@type='bibliography']. Then, process bibliographic references
# (Author+Date or equivalent). This order because we need to tell from the get
# go where a reference will point, which requires us to know which entries are
# present in the file-specific bibliography and which are not. (The latter
# need to be presented within the project-wide bibliography.)
def gather_biblio(p):
	for bibl in p.tree.find(".//listBibl/bibl[ptr]"):
		ptr = bibl.first("ptr")
		short_title = ptr["target"].removeprefix("bib:")
		if not short_title or short_title == "AuthorYear_01":
			continue
		siglum = bibl["n"]
		if siglum:
			# The same siglum might erroneously be used for several
			# entries. In this case, map it to the first one (since
			# this is what we are doing with duplicate short titles).
			p.sigla.setdefault(short_title, siglum)
		# The same short title might be used in several bibliographic
		# entries, possibly with different sigla, page ranges, etc.,
		# even though this is forbidden by the schema. If this happens,
		# we will just display the duplicates, but we should also take
		# care not to generate duplicate anchors in the HTML. XXX not done so far
		if short_title not in p.bib_entries:
			entry = biblio.lookup_entry(short_title)
			p.bib_entries[short_title] = entry

@handler("div[regex('edition|apparatus|commentary|bibliography', @type)]")
def parse_main_div(p, div):
	p.push(tree.Tag(div["type"], lang=div.notes["assigned_lang"]))
	add_div_heading(p, div, div["type"].title())
	p.dispatch_children(div)
	assert hasattr(p.document, div["type"])
	setattr(p.document, div["type"], p.pop())

@handler("div[@type='translation']")
def parse_div_translation(p, div):
	def make_translation_heading():
		resps = div["resps"]
		if resps:
			# If translators names are the exact same set of people
			# who edited the inscription, do not display them.
			resps = resps.split()
			editors = set(ident for ident, name in p.document.editors)
			if editors != set(resps):
				resps = None
		p.append("Translation")
		# Only display the traduction's language if not English.
		if div.notes["assigned_lang"].language != "eng":
			# The following should never fail, otherwise there is a
			# bug in the languages module.
			(name,) = common.db("texts").execute("""
				select name from langs_list where id = ?""",
				(div.notes["assigned_lang"].language,)).fetchone()
			p.append(f" into {name}")
		if (sources := div["source"]):
			# Print in this order: bibliographic sources and names
			# of DHARMA members. Because we assume that, if both
			# are given, the DHARMA member is using an existing
			# traduction that he is trying to improve, so the
			# primary translator is the one mentioned in the
			# bibliography.
			p.append(" by ")
			finish_list = not resps
			append_sources(p, sources.split(), finish_list)
			if resps:
				p.append(", ")
				append_names(p, resps)
		elif resps:
			p.append(" by ")
			append_names(p, resps)
	p.push(tree.Tag("translation", lang=div.notes["assigned_lang"]))
	add_div_heading(p, div, make_translation_heading)
	p.dispatch_children(div)
	p.document.translation.append(p.pop())

@handler("div[@type='textpart']")
@handler("div")
def parse_div_textpart(p, div):
	"""For div[@type='textpart']. We treat divs without a @type as if they
	had @type='textpart'.

	Within inscriptions, <div> shouldn't nest, except that we can have
	<div type="textpart"> within <div type="edition">.
	The DHARMA_INSEC* stuff don't follow the INS schema, too different.
	We expect:
	<div type="textpart" n="..."><head>...</head>?<note>?
	"""
	def make_textpart_heading():
		subtype = div["subtype"] or "part"
		p.append(common.sentence_case(subtype))
		if (n := get_n(div)):
			p.append(f" {n}")
	p.push(tree.Tag("div", lang=div.notes["assigned_lang"]))
	add_div_heading(p, div, make_textpart_heading)
	p.dispatch_children(div)
	p.join() # </div>

def add_div_heading(p, div, dflt):
	p.push(tree.Tag("head"))
	if (head := div.first("stuck-child::head")):
		# User-specified heading, use it.
		p.top["lang"] = head.notes["assigned_lang"]
		p.dispatch_children(head)
		p.visited.add(head)
		# We support notes here because the guide says so, but putting
		# them within <head>< should be preferred.
		note = head.first("stuck-following-sibling::note")
	else:
		# All generated headings are in English.
		p.top["lang"] = "eng latin"
		# No user-specified heading, generate one.
		if callable(dflt):
			dflt()
		else:
			assert isinstance(dflt, str)
			p.append(dflt)
		note = div.first("stuck-child::note")
	if note:
		p.dispatch(note)
		p.visited.add(note)
	p.join() # </head>

def append_names(p, resps):
	for i, resp in enumerate(resps):
		resp = resp.removeprefix("part:")
		if i == 0:
			pass
		elif i < len(resps) - 1:
			p.append(", ")
		else:
			p.append(" and ")
		p.append(fetch_resp(resp))

def append_sources(p, bib_refs, finish_list=True):
	refs = []
	for ref in bib_refs:
		ref = ref.removeprefix("bib:")
		common.append_unique(refs, ref)
	for i, ref in enumerate(refs):
		ref = ref.removeprefix("bib:")
		if i == 0:
			pass
		elif i < len(refs) - 1:
			p.append(", ")
		elif finish_list:
			p.append(" and ")
		p.append(p.bib_reference(ref))

@handler("*")
def parse_remainder(self, node):
	print(f"UNKNOWN {node!r}", file=sys.stderr)
	self.append(node.text())

def process_file(file):
	t = tree.parse_string(file.data, path=file.full_path)
	only_body = False
	if file.name.startswith("DHARMA_DiplEd") or file.name.startswith("DHARMA_CritEd"):
		only_body = True
	return process_tree(t, only_body)

def process_tree(t, only_body=False, handlers=HANDLERS):
	languages.assign_languages(t)
	p = Parser(t, handlers=handlers)
	# When we are parsing the file, not to display it but to extract
	# metadata for the catalog, we only need to parse the teiHeader and
	# can ignore the text body. Furthermore, we need to remove footnotes
	# in the metadata; they should not be shown within the catalog.
	# (Alternatively, we could have a mouseover, but not sure it would be
	# worth it.)
	if only_body:
		for path in ("/TEI/teiHeader//title//note", "/TEI/text"):
			for node in t.find(path):
				p.visited.add(node)
	# Process the bibliography first, to gather sigla.
	# We do this early because we might need to access bibliographical
	# data when parsing e.g. the //teiHeader//msContents/summary. Note that
	# we can't even parse the div[@type='bibliography'] before other stuff
	# in the file, because this div might itself reference bibliography
	# entries. We thus need to go directly for the listBibl/bibl items.
	gather_biblio(p)
	r = tree.Tree()
	p.push(r)
	p.dispatch(t.root)
	assert r.empty, r.xml()
	return p.document

if __name__ == "__main__":
	from dharma import texts
	@common.transaction("texts")
	def main():
		path = os.path.abspath(sys.argv[1])
		try:
			f = texts.File("/", path)
			doc = process_file(f)
			print(doc.serialize().xml())
			#ret = doc.to_html()
			#print(ret.title.xml())
		except BrokenPipeError:
			pass
	main()
