"""
Stuff for dealing with languages and scripts.

The language and script data are stored in project_documentation: see
DHARMA_languages and DHARMA_scripts.

For ISO 639-3 (3-letters codes for languages), the authority is:
https://iso639-3.sil.org.

For ISO 639-5 (3-letters codes for language families), the authority is:
https://www.loc.gov/standards/iso639-5/index.html.

For scripts, we use dharma-internal codes instead of ISO ones. See
DHARMA_scripts in project-documentation.

For languages we don't can't determine, we use the value `und`. There is also `zxx`, for non-linguistic contents.

Pour les facettes, on devrait être en mesure de calculer la longueur d'un texte
en phonèmes, en caractères, en lignes, en pages, en divisions, en paragraphes,
etc.

Goals for languages/scripts:

* need to be able to search for passages in a given language or in a given
  script
* need to be able to look for files that use some given language (includes
  modern languages, like e.g. "find all inscriptions translated into French").
* need to indicate, in the generated html, that portion X is in a given
  language, for better hyphenation in the browser
* need to tell the user which languages are used in the edition; in this
  context, should omit source_other for scripts and langs.
* need to tell which languages are used anywhere in the file
* In addition, should have stats (number of chars, of clusters, etc.) for each
  lang, script, pair of script+lang. But might be easier to gather stats like
  this if we use the internal representation instead of the TEI one.
"""

from dharma import common, texts, tree

def scripts_hierarchy_to_html() -> tree.Tag:
	"""Convert the script hierarchy to an HTML representation.

	We use the data present in the db instead of the data defined in this
	module to be sure we always use the same version of the data."""
	db = common.db("texts")
	row = db.execute("""
	select scripts_list.rid as rid, id, name, inverted_name
	from scripts_list natural join scripts_closure
	where root is null""").fetchone()
	assert row
	root = tree.Tag("ul")
	if not row:
		return root
	li = tree.Tag("li")
	root.append(li)
	stack = [(li, row)]
	while stack:
		node, row = stack.pop()
		node.append(row["name"])
		node.append(" [")
		span = tree.Tag("span", class_="monospace")
		span.append(row["id"])
		node.append(span)
		node.append("]")
		child_rows = db.execute("""
		select scripts_list.rid as rid, id, name, inverted_name
		from scripts_list natural join scripts_closure
		where root = ? and depth = 1""", (row["rid"],)).fetchall()
		if child_rows:
			children = tree.Tag("ul")
			for child_row in child_rows:
				child = tree.Tag("li")
				children.append(child)
				stack.append((child, child_row))
			node.append(children)
	return root


######################## For annotating TEI documents ##########################

class Descriptor:
	"""
	Dummy class for holding both a language and a script in a single object.
	"""

	def __init__(self, language="und", script="latin"):
		self.language: str = language
		self.script: str = script

	def __repr__(self):
		return f"Descriptor({self.language}, {self.script})"

	def _fields(self):
		return self.language, self.script

	def __eq__(self, other):
		return self._fields() == other._fields()

	def __hash__(self):
		return hash(self._fields())

	def __str__(self):
		return f"{self.language} {self.script}"

	def copy(self):
		return Descriptor(self.language, self.script)

def _extract_language_ident(node) -> str | None:
	lang = node["lang"].split("-", 1)[0]
	if not lang:
		return
	db = common.db("texts")
	(lang,) = db.execute("""
	select langs_list.id
	from langs_list join langs_by_code
		on langs_list.id = langs_by_code.id
	where langs_by_code.code = ? or langs_by_code.code = ?
	order by langs_by_code.id desc
	""", (lang, lang + "_other")).fetchone() or (None,)
	return lang

def _extract_script_ident(node) -> str | None:
	script_elems = node["rendition"].split()
	script = None
	for elem in script_elems:
		if elem.startswith("class:"):
			tmp = elem.removeprefix("class:")
			if tmp == "undetermined":
				tmp = None
			script = tmp
	if not script:
		return
	db = common.db("texts")
	(script,) = db.execute("""
	select scripts_list.id
	from scripts_list join scripts_by_code
		on scripts_list.id = scripts_by_code.id
	where scripts_by_code.code = ? or scripts_by_code.code = ?
	order by scripts_list.id desc
	""", (script, script + "_other")).fetchone() or (None,)
	return script

def _extract_language_info(node) -> Descriptor | None:
	if (lang := node.notes.get("lang")):
		return lang
	lang_id = _extract_language_ident(node)
	script_id = _extract_script_ident(node)
	# For marking up Grantha text, an old (legacy) convention was to use
	# <hi rend="grantha"> (because Grantha is supposed to be put in bold)
	# instead of @rendition="class:grantha maturity:regional". The use of
	# <hi rend="grantha"> should be abandoned eventually. In the meantime,
	# we manually change the script id when we find this encoding.
	if not script_id and node.name == "hi" and node["rend"] == "grantha":
		script_id = "grantha"
	if not lang_id and not script_id:
		return
	parent_lang = node.parent.notes["lang"]
	node_lang = parent_lang.copy()
	if lang_id:
		node_lang.language = lang_id
	if script_id:
		node_lang.script = script_id
	return node_lang

##################### For annotating internal documents ########################

def complete_internal(t: tree.Tree):
	"""Set a @lang attribute on all elements."""
	for child in t:
		_complete_internal_any(child)

def _complete_internal_any(node):
	if not isinstance(node, tree.Tag):
		return
	langs = set()
	for child in node:
		if not isinstance(child, tree.Tag):
			continue
		if (lang := child["lang"]):
			langs.add(lang)
	if len(langs) == 1:
		node["lang"] = langs.pop()
	for child in node:
		_complete_internal_any(child)


def finish_internal(node: tree.Branch):
	"""
	Examines all nodes in this subtree and removes the @lang attribute from
	elements that do not have at least one non-blank string as child. In
	other words, this makes sure that all non-blank strings in this subtree
	have a parent with a @lang, and that only such nodes have a @lang.
	`tree.Tree` objects should not have strings as children.
	"""
	if isinstance(node, tree.Tag):
		# Only keep @lang if the node actually contains text. Thus,
		# all tags that have at least one non-empty string as child
		# have a @lang, and only them.
		for child in node:
			if not isinstance(child, tree.String):
				continue
			if len(child) > 0 and not child.isspace():
				break
		else:
			del node["lang"]
	for child in node:
		if isinstance(child, tree.Branch):
			finish_internal(child)

########################## Database construction ###############################

dependencies = {"DHARMA_languages.tsv", "DHARMA_scripts.xml"}

def update():
	_update_langs()
	_update_scripts()

def _update_langs():
	db = common.db("texts")
	recs, index = _load_langs()
	db.execute("delete from langs_by_code")
	db.execute("delete from langs_by_name")
	db.execute("delete from langs_list")
	for rec in recs:
		db.execute("""
			insert into langs_list(rid, id, name, inverted_name,
	     			iso, custom, dharma, parent)
			values(:rid, :id, :name, :inverted_name, :iso,
				:custom, :dharma, :parent)""", rec)
		db.execute("insert into langs_by_name(id, name) values(?, ?)",
			(rec["id"], common.normalize_text(rec["name"])))
	for code, rec in sorted(index.items()):
		db.execute("insert into langs_by_code(code, id) values(?, ?)", (code, rec["id"]))

def _init_base_recs():
	# Define core taxonomic categories with mandatory inverted_name
	recs = [{"id": "lang", "name": "Language", "inverted_name": "Language", "iso": None, "custom": True, "dharma": True, "parent": None}]
	index = {rec["id"]: rec for rec in recs}
	return recs, index

def _process_iso3(tbl3, tbl3_bis, recs, index):
	# Initialize ISO 639-3 records with a default inverted_name
	for row in tbl3:
		rec = {"id": row["Id"], "name": row["Ref_Name"], "inverted_name": row["Ref_Name"], "iso": 3, "custom": False, "dharma": False, "parent": "lang"}
		recs.append(rec)
		for field in ("Id", "Part2b", "Part2t", "Part1"):
			if row.get(field):
				index[row[field]] = rec
	for row in tbl3_bis:
		rec = index.get(row["Id"])
		if rec and rec["name"] == row["Print_Name"]:
			rec["inverted_name"] = row["Inverted_Name"]
	return recs, index

def _process_iso5(tbl5, recs, index):
	# Add ISO 639-5 families
	for row in tbl5:
		rec = {"id": row["code"], "name": row["Label (English)"], "inverted_name": row["Label (English)"], "iso": 5, "custom": False, "dharma": False, "parent": "lang"}
		recs.append(rec)
		index[rec["id"]] = rec
	return recs, index

def _process_dharma(tbl0, recs, index):
	# Update or create records based on DHARMA specific metadata
	for row in tbl0:
		rec = index.get(row["Id"])
		if not rec:
			rec = {"id": row["Id"], "name": row["Print_Name"], "inverted_name": row["Inverted_Name"], "iso": None, "custom": True}
			recs.append(rec)
			index[rec["id"]] = rec
		else:
			rec["custom"] = False
			if row["Print_Name"] and row["Print_Name"] != rec["name"]:
				rec.update({"name": row["Print_Name"], "custom": True})
			if row["Inverted_Name"] and row["Inverted_Name"] != rec["inverted_name"]:
				rec.update({"inverted_name": row["Inverted_Name"], "custom": True})
		rec.update({"dharma": True, "parent": "lang"})
	return recs, index

def _finalize_recs(recs, index):
	# Final check and parent ID resolution
	assert all("inverted_name" in rec for rec in recs)
	for rid, rec in enumerate(recs, 1):
		rec["rid"] = rid
	for rec in recs:
		if rec["parent"] is not None:
			rec["parent"] = index[rec["parent"]]["rid"]
	return recs, index

def _load_langs():
	# Master function for language data loading
	t3 = common.fetch_tsv("https://iso639-3.sil.org/sites/iso639-3/files/downloads/iso-639-3.tab")
	t3b = common.fetch_tsv("https://iso639-3.sil.org/sites/iso639-3/files/downloads/iso-639-3_Name_Index.tab")
	t5 = common.fetch_tsv("http://id.loc.gov/vocabulary/iso639-5.tsv")
	t0 = common.fetch_tsv(texts.save("project-documentation", "DHARMA_languages.tsv"))
	recs, index = _init_base_recs()
	recs, index = _process_iso3(t3, t3b, recs, index)
	recs, index = _process_iso5(t5, recs, index)
	recs, index = _process_dharma(t0, recs, index)
	return _finalize_recs(recs, index)

def _update_scripts():
	db = common.db("texts")
	db.execute("delete from scripts_by_code")
	db.execute("delete from scripts_list")
	_insert_script(db, _load_scripts())

def _insert_script(db, script):
	db.execute("""
		insert into scripts_list(rid, id, name, inverted_name, parent)
		values(:rid, :id, :name, :inverted_name, :parent)""", script)
	for code in script["ids"]:
		db.execute("""insert into scripts_by_code(code, id)
			values(?, ?)""", (code, script["id"]))
	for child in script["children"]:
		_insert_script(db, child)

def _load_scripts():
	f = texts.File("project-documentation", "DHARMA_scripts.xml")
	common.db("texts").save_file(f)
	t = tree.parse_string(f.text)
	root = _process_script_node(t.root)
	_patch_scripts(root)
	_make_hierarchy(root)
	return root

def _process_script_node(script):
	rec = {}
	rec["ids"] = []
	for sid in script.find("id"):
		sid = sid.text()
		if not sid:
			continue
		common.append_unique(rec["ids"], sid)
	if len(rec["ids"]) < 1:
		raise Exception("bad value")
	rec["id"] = rec["ids"][0]
	name = script.first("name")
	if name:
		name = name.text()
	if not name:
		name = rec["ids"][0]
	rec["name"] = name
	inverted_name = script.first("inverted_name")
	if inverted_name:
		inverted_name = inverted_name.text()
	if not inverted_name:
		inverted_name = rec["name"]
	rec["inverted_name"] = inverted_name
	rec["children"] = []
	for child in script.find("script"):
		child = _process_script_node(child)
		rec["children"].append(child)
	return rec

def _patch_scripts(script):
	"""Add extra complement categories to the scripts hierarchy.

	In our TEI encoding, people have the option to use a non-leaf script
	category (like "arabic") or a leaf script category (like "jawi"). For
	search, we want all assigned scripts to be leaves. Thus, for the
	internal representation, we create complementary categories in such a
	way that all branches have a complementary leaf. For "arabic", we thus
	have two subcategories "jawi" and "arabic_other"; the latter is used
	when the user indicated "arabic", so that the identifier "arabic"
	remains available for search and does mean "anything in arabic, whether
	jawi or not".
	"""
	if not script["children"]:
		return
	compl = {
		"ids": [sid + "_other" for sid in script["ids"]],
		"name": script["name"] + " (other)",
		"inverted_name": script["inverted_name"] + " (other)",
		"children": [],
	}
	compl["id"] = compl["ids"][0]
	script["children"].append(compl)
	for child in script["children"]:
		_patch_scripts(child)

def _make_hierarchy(root, rid=0, parent=None):
	"Add record ids and pointers to parent records."
	rid += 1
	root["rid"] = rid
	root["parent"] = parent
	for child in root.get("children", []):
		rid = _make_hierarchy(child, rid, root["rid"])
	return rid

def annotate_for_ingestion(t: tree.Tree):
	add_lang_info(t)
	if (ed := t.first("//div[@type='edition']")):
		add_editorial_info(ed)

def add_lang_info(node, parent_lang=Descriptor("eng", "latin")):
	"""
	Annotates the given subtree with languages and scripts. Annotations are
	stored in `tree.Node.notes["lang"]`, which is associated with a
	`Descriptor`.

	Languages and scripts are assigned recursively, looking at @lang (for
	the language) and @rendition (for the script). These two attributes are
	inherited separately. Thus, if a node does not have a @lang but does
	have a @rendition, its language will be set to the one of its parent
	node and its script will be extracted from @rendition. Idem for the reverse.

	There are exceptions to this inheritance rule:

	1) If the element is "foreign" and does not have a @lang, then its lang
	is set to "und" and its script to "latin". Indeed, the EGD says that
	foreign with @lang is to be used for marking up a piece of text in some
	indeterminate source language. It is in fact used just for the visual
	effect.

	2) Likewise, if the element is div[@type='edition'] and does not have a
	@lang, we assign it the language "und" and the script "latin". We know
	that the edition div is in some indeterminate source language, but we
	cannot tell which one, so "und" is to be preferred.

	It should be noted that, within the div[@type='apparatus'], "lem" and
	"rdg" are typically not assigned a @lang or @rendition. They thus
	inherit the parent language, which is very likely to be "eng". The langs
	and scripts we assign to the apparatus division are thus likely not to
	be correct. But we don't really care, because we don't try to do
	anything interesting with the apparatus, like making it searchable.
	"""
	# Don't reprocess the node if already done. We assume that, if the node
	# has a "lang" note, its descendants have been processed as well.
	if node.notes.get("lang") is not None:
		return
	match node:
		case tree.Tree():
			node.notes["lang"] = parent_lang
			for child in node:
				add_lang_info(child, parent_lang)
		case tree.Tag():
			lang = _extract_language_info(node)
			if not lang:
				if node.name == "foreign" or node.name \
					== "div" and node["type"] == "edition":
					lang = Descriptor("und", "latin")
				else:
					lang = parent_lang
			node.notes["lang"] = lang
			for child in node:
				add_lang_info(child, lang)
		case tree.String():
			node.notes["lang"] = parent_lang

def add_editorial_info(node, parent_editorial=False):
	"""
	Annotates a node with information indicating whether it is "editorial",
	viz. if the text it contains belongs to the original text (in which case
	it is not deemed "editorial") or not (in which case it is deemed
	"editorial"). We add an "editorial" key with a boolean in the notes
	(`.notes`) of each node.

	This is only relevant for div[@type='edition']. Within this div, there
	are titles, notes, etc. inserted by the editor that do not belong to the
	edited text. We don't want these passages to be treated as if they
	belonged to the edited text when we are extracting the languages of the
	edition. Otherwise, most edited texts would end up with a modern
	language (like English) as one of their edition languages.

	Note that this does _not_ concern editorial interventions (like "add",
	"del", etc.), only parts of the editions that are inserted by the editor
	and that we think are in a modern language.

	No measures have been taken in the encoding to distinguish unambiguously
	what is editorial from what is not, thus we resort to an approximation.
	We assume that an element is editorial iff it is one of "note", "head",
        "bibl", "desc", "figDesc" and "label" or a descendant of them. The
	proper method to distinguish "editorial" nodes from non-"editorial" ones
	would be to use a boolean in encoded XML files, but it is too late to do
	that now.

	Before coming up with this, we defined two types of languages and
	scripts: "source" (for languages and scripts we expect to find in the
	div[@type='edition']) and "study" (for languages and scripts we expect
	to find in the translation, for instance; typically the language and
	script used by the editor). The assumption was that a language would
	either be a "source" language or a "study" language, not both, which
	turned out not to be true (some inscriptions have passages in a "modern"
	language; see e.g. ~DHARMA_INSSIIv26p0i0069.xml, which has passages in
	Dutch). Furthermore, it was annoying to systematically classify
	languages in two categories. The current solution seems preferable.
	"""
	if node.notes.get("editorial") is not None:
		return
	match node:
		case tree.Tree():
			node.notes["editorial"] = parent_editorial
			for child in node:
				add_editorial_info(child, parent_editorial)
		case tree.Tag():
			editorial = parent_editorial or node.name in {"note",
				"head", "bibl", "desc", "figDesc", "label"}
			node.notes["editorial"] = editorial
			for child in node:
				add_editorial_info(child, editorial)
		case tree.String():
			node.notes["editorial"] = parent_editorial

@common.transaction("texts")
def _cmd_update_db():
	update()

@common.transaction("texts")
def _cmd_print_stuff():
	import os, sys
	from dharma import ingest, common, texts, enrich
	path = os.path.abspath(sys.argv[1])
	f = texts.File("/", path)
	t = ingest.process_file(f)
	enrich.process(t)
	enrich.make_pretty_printable(t)
	root = t.first("/document")
	assert root
	for s in root.strings():
		text = s.data.strip()
		if not text:
			continue
		assert s.parent and isinstance(s.parent, tree.Tag)
		assert s.parent["lang"], s.parent.xml()
		print(s.parent["lang"], text, sep="\t")

if __name__ == "__main__":
	try:
		_cmd_print_stuff()
	except BrokenPipeError:
		pass
