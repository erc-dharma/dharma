"""
XXX


penser à hi rend="grantha" où on doit générer le bon script ([@rendition]) et
  aussi inversement quand le @rendition réfère à grantha, mettre le texte en gras.

Retirer distinction entre assigned lang et inferred lang, avoir une seule catégorie lang.

Pour les langues, il faut avoir une hiérarchie à au moins deux niveaux (source, study). Et il faut la représenter dans le csv (en ajoutant les noms source et study pour chaque colonne).

Ajouter tests. 1: rendition sur la div

Pour les facettes, on devrai être en mesure de calculer la longueur d'un texte en phonèmes, en caractères, en lignes, en pages, en divisions, en paragraphes, etc.


Si tous les éléments enfants d'un élément donné ont la même langue et que cette langue a été expréssément indiquée par l'utilisateur, on peut sans doute considérer que la langue indiquée par l'utilisateur sur l'élément donné doit être ignorée. Mais il faut être en mesure de dire si la langue est ou non indiquée par l'utilisateur, donc mieux vaut faire ça sur le TEI. Et on doit ino



need to annotate the internal tree with language infos, and do so for both assigned and inferred; or maybe do it just for assigned, and deduce inferred from the internal repr? yes, maybe better.

Pour l'assignement des langues, vérifier que tout segment de texte  a un parent pourvu de l'attribut lang.

Expliquer différences entre assignement des langues dans le tei et dans la représentation interne. Noter qu'on ne fait pas ce qu'il faut pour l'apparatus; on pourrait éventuellement simplement assigner 'source' aux lem et rdg.

Au tableau des scripts by code, ajouter version avec l'autre r voyelle, éventuellement tout sans diacritiques. Oui en fait ajouter tout sans diacritiques et ajouter le vrai identifiant dans le tableau principal.

For scripts, define short identifiées with three lettres, like for iso, for use in search.

To the langs and scripts display, also display stats related to language usage. And also do that for the repos display.
"""

"""Stuff for dealing with languages and scripts.

Goals for languages/scripts:

* need to be able to search for passages in a given language or in a given script
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

For ISO 639-3 (languages), the authority is https://iso639-3.sil.org.

For ISO 639-5 (language families), the authority is
https://www.loc.gov/standards/iso639-5/index.html.

For scripts, we use dharma-internal codes.
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

# We interpret @xml:lang only on these elements. If another element has an
# @xml:lang, we act as if it did not exist, and assign to it the language of its
# parent node.
#
# This must be kept in sync with the TEI parsing code.
#
# The reason we do not take all elements into account is that this would entail
# much modifications to the TEI parsing code (because we would need to pass
# a @lang parameter to most newly created elements).
tei_language_sensitive = {
	"div", "note", "p", "ab", "lg", "q", "head", "quote",
	"label", "foreign", "seg",
	"lem", "rdg", "ex",
}

class LanguageInfo:

	def __init__(self, language="eng", script="latin", is_source=False):
		self.language = language
		self.is_source = is_source
		self.script = script

	def __repr__(self):
		return f"LanguageInfo({self.language}, {self.script})"

	def _fields(self):
		return self.language, self.script

	def __eq__(self, other):
		return self._fields() == other._fields()

	def __hash__(self):
		return hash(self._fields())

	def __str__(self):
		return f"{self.language} {self.script}"

	def copy(self):
		import copy
		return copy.copy(self)

def should_bubble_up(root):
	langs = set()
	for child in root:
		match child:
			case tree.String():
				if len(child) == 0 or child.isspace():
					continue
			case tree.Comment() | tree.Instruction():
				continue
			case tree.Tag("head"):
				continue
		langs.add(child.notes["inferred_lang"])
	if len(langs) == 1:
		return langs.pop()

def recurse(root):
	match root:
		case tree.Tree():
			root.notes["assigned_lang"] = LanguageInfo()
			for child in root:
				recurse(child)
		case tree.Tag():
			root.notes["assigned_lang"] = extract_language_info(root)
			for child in root:
				recurse(child)
			if (lang := should_bubble_up(root)):
				root.notes["assigned_lang"] = lang
		case _:
			root.notes["assigned_lang"] = root.parent.notes["assigned_lang"]
	root.notes["inferred_lang"] = root.notes["assigned_lang"]

def language_significant(root):
	match root:
		case tree.Tree():
			raise Exception
		case tree.Tag():
			return True
		case tree.Comment():
			return False
		case tree.String():
			return len(root) > 0 and not root.isspace()
		case tree.Instruction():
			return False

def extract_language_ident(node):
	dflt = (None, None)
	lang = node["lang"].split("-")[0]
	if not lang:
		return dflt
	db = common.db("texts")
	lang, rid = db.execute("""
	select langs_list.id, langs_list.rid
	from langs_list join langs_by_code
		on langs_list.id = langs_by_code.id
	where langs_by_code.code = ? or langs_by_code.code = ?
	order by langs_by_code.id desc
	""", (lang, lang + "_other")).fetchone() or dflt
	if not lang:
		return dflt
	is_source = db.execute("""
	select 1 from langs_closure
	where root = (select rid from langs_list where id = 'source')
	and rid = ?""", (rid,)).fetchone()
	return lang, bool(is_source)

def extract_script_ident(node):
	dflt = (None, None)
	script_elems = node["rendition"].split()
	script = None
	for elem in script_elems:
		if elem.startswith("class:"):
			tmp = elem.removeprefix("class:")
			if tmp == "undetermined":
				tmp = None
			script = tmp
	if not script:
		return dflt
	db = common.db("texts")
	script, rid = db.execute("""
	select scripts_list.id, scripts_list.rid
	from scripts_list join scripts_by_code
		on scripts_list.id = scripts_by_code.id
	where scripts_by_code.code = ? or scripts_by_code.code = ?
	order by scripts_list.id desc
	""", (script, script + "_other")).fetchone() or dflt
	if not script:
		return dflt
	is_source = db.execute("""
	select 1 from scripts_closure
	where root = (select rid from scripts_list where id = 'source')
	and rid = ?""", (rid,)).fetchone()
	return script, bool(is_source)

def extract_language_info(node):
	if (lang := node.notes.get("assigned_lang")):
		return lang
	parent_lang = node.parent.notes["assigned_lang"]
	if node.name not in tei_language_sensitive:
		return parent_lang
	lang_id, lang_is_source = extract_language_ident(node)
	script_id, _ = extract_script_ident(node)
	if not lang_id and not script_id:
		return parent_lang
	node_lang = parent_lang.copy()
	if lang_id:
		node_lang.language = lang_id
		node_lang.is_source = lang_is_source
	if script_id:
		node_lang.script = script_id
	else:
		# If the parent has a source language and the child has a study
		# one, don't inherit the parent's script but reset it to
		# "latin". Conversely, if the parent has a study language
		# language and the child a source one, reset the script to
		# "source_other".
		if parent_lang.is_source and not node_lang.is_source:
			node_lang.script = "latin"
		if not parent_lang.is_source and node_lang.is_source:
			node_lang.script = "source_other"
	return node_lang

def assign_languages(t):
	"""For assigning languages, we follow the basic inheritance rule: if a
        tag does not have an @xml:lang, it is assigned the language assigned its
        parent. But there are exceptions:

        ¶ If the tag is "foreign", "lem" or "rdg" and does not have an
        @xml:lang, we assume it is in some source language (as per the guide)
        and assign it a generic language named "source" and a script named
        "source" as well. These represent any source language (per contrast with
        languages used in translations).

	Furthermore, we store two language values per node:

	¶ Assigned language. Assigned when traversing the tree top-down. This
        follows what people explicitly indicate for @xml:lang.
	"""
	for node in t.find(".//*[name()='foreign' or name()='lem' or name()='rdg' or (name()='div' and @type='edition')]"):
		assert not node.notes.get("assigned_lang")
		lang, lang_is_source = extract_language_ident(node)
		if not lang or not lang_is_source:
			lang = "source_other"
		script, script_is_source = extract_script_ident(node)
		if not script or not script_is_source:
			script = "source_other"
		node.notes["assigned_lang"] = LanguageInfo(language=lang,
			script=script, is_source=True)
	recurse(t)

##################### For annotating internal documents ########################

def complete_internal(t: tree.Tree):
	"""Set a @lang attribute on all elements."""
	for child in t:
		complete_internal_any(child, "eng latin")

def complete_internal_milestone(node, lang):
	node["lang"] = "zxx latin"
	for child in node:
		match child:
			case tree.Tag("span") if node["class"] == "fw-contents":
				complete_internal_any(child, lang)
			case tree.Tag():
				complete_internal_milestone(child, lang)

def complete_internal_any(node, lang):
	match node:
		case tree.Tag("npage") | tree.Tag("nline") | tree.Tag("ncell"):
			# In this case, treat this node and all its descendants
			# as if their @lang were `zxx` (non-linguistic data).
			# But if one of this node's descendants is a
			# span[@class='fw-contents'], treat it normally.
			complete_internal_milestone(node, lang)
		case tree.Tag():
			if node["lang"]:
				lang = node["lang"]
			else:
				node["lang"] = lang
			for child in node:
				complete_internal_any(child, lang)

def finish_internal(node: tree.Branch):
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

def update_db():
	update_langs()
	update_scripts()

def update_langs():
	db = common.db("texts")
	recs, index = load_langs()
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

def load_langs():
	tbl3 = common.fetch_tsv("https://iso639-3.sil.org/sites/iso639-3/files/downloads/iso-639-3.tab")
	tbl3_bis = common.fetch_tsv("https://iso639-3.sil.org/sites/iso639-3/files/downloads/iso-639-3_Name_Index.tab")
	tbl5 = common.fetch_tsv("http://id.loc.gov/vocabulary/iso639-5.tsv")
	tbl0 = common.fetch_tsv(texts.save("project-documentation", "DHARMA_languages.tsv"))
	recs = [
	{
		"id": "lang",
		"name": "Any Language",
		"inverted_name": "Any Language",
		"iso": None,
		"custom": True,
		"dharma": True,
		"parent": None,
	}, {
		"id": "source",
		"name": "Source Language",
		"inverted_name": "Source Language",
		"iso": None,
		"custom": True,
		"dharma": True,
		"parent": "lang",
	}, {
		"id": "study",
		"name": "Study Language",
		"inverted_name": "Study Language",
		"iso": None,
		"custom": True,
		"dharma": True,
		"parent": "lang",
	},  {
		"id": "source_other",
		"name": "Source Language (other)",
		"inverted_name": "Source Language (other)",
		"iso": None,
		"custom": True,
		"dharma": True,
		"parent": "source",
	}, {
		"id": "study_other",
		"name": "Study Language (other)",
		"inverted_name": "Study Language (other)",
		"iso": None,
		"custom": True,
		"dharma": True,
		"parent": "study",
	}]
	index = {}
	for rec in recs:
		add_to_index(rec["id"], index, rec)
	for row in tbl3:
		assert row["Id"]
		rec = {
			"id": row["Id"],
			"name": row["Ref_Name"],
			"iso": 3,
			"custom": False,
			"dharma": False,
			"parent": "source",
		}
		recs.append(rec)
		# "Part2b", "Part2t", "Part1" are alternate language codes.
		for field in ("Id", "Part2b", "Part2t", "Part1"):
			add_to_index(row[field], index, rec)
	for row in tbl3_bis:
		rec = index[row["Id"]]
		if rec["name"] == row["Print_Name"]:
			assert not rec.get("inverted_name")
			rec["inverted_name"] = row["Inverted_Name"]
	for row in tbl5:
		rec = {
			"id": row["code"],
			"name": row["Label (English)"],
			"inverted_name": row["Label (English)"],
			"iso": 5,
			"custom": False,
			"dharma": False,
			"parent": "source",
		}
		recs.append(rec)
		add_to_index(rec["id"], index, rec)
	for row in tbl0:
		assert not "-" in row["Id"]
		rec = index.get(row["Id"])
		if not rec:
			rec = {
				"id": row["Id"],
				"name": row["Print_Name"],
				"inverted_name": row["Inverted_Name"],
				"iso": None,
				"custom": True,
			}
			recs.append(rec)
			add_to_index(rec["id"], index, rec)
		else:
			rec["custom"] = False
			if row["Print_Name"] and row["Print_Name"] != rec["name"]:
				rec["name"] = row["Print_Name"]
				rec["custom"] = True
			if row["Inverted_Name"] and row["Inverted_Name"] != rec["inverted_name"]:
				rec["inverted_name"] = row["Inverted_Name"]
				rec["custom"] = True
		rec["dharma"] = True
		rec["parent"] = row["type"] or "source"
	assert all("inverted_name" in rec for rec in recs)
	for rid, rec in enumerate(recs, 1):
		rec["rid"] = rid
	root = None
	for rec in recs:
		if rec["parent"] is None:
			assert root is None
			root = rec
			continue
		rec["parent"] = index[rec["parent"]]["rid"]
	return recs, index

def add_to_index(code, index, rec):
	if not code:
		return
	assert not code in index or index[code] is rec
	index[code] = rec

def update_scripts():
	db = common.db("texts")
	db.execute("delete from scripts_by_code")
	db.execute("delete from scripts_list")
	insert_script(db, load_scripts())

def insert_script(db, script):
	db.execute("""
		insert into scripts_list(rid, id, name, inverted_name, parent)
		values(:rid, :id, :name, :inverted_name, :parent)""", script)
	for code in script["ids"]:
		db.execute("""insert into scripts_by_code(code, id)
			values(?, ?)""", (code, script["id"]))
	for child in script["children"]:
		insert_script(db, child)

def load_scripts():
	f = texts.File("project-documentation", "DHARMA_scripts.xml")
	common.db("texts").save_file(f)
	t = tree.parse_string(f.text)
	root = process_script_node(t.root)
	patch_scripts(root)
	make_hierarchy(root)
	return root

def process_script_node(script):
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
		child = process_script_node(child)
		rec["children"].append(child)
	return rec

def patch_scripts(script):
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
		patch_scripts(child)

def make_hierarchy(root, rid=0, parent=None):
	"Add record ids and pointers to parent records."
	rid += 1
	root["rid"] = rid
	root["parent"] = parent
	for child in root.get("children", []):
		rid = make_hierarchy(child, rid, root["rid"])
	return rid

@common.transaction("texts")
def cmd_update_db():
	update_db()

@common.transaction("texts")
def cmd_print_stuff():
	import os, sys
	from dharma import tei, common, texts, patch
	path = os.path.abspath(sys.argv[1])
	f = texts.File("/", path)
	t = tei.process_file(f).serialize()
	patch.process(t)
	patch.make_pretty_printable(t)
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
		cmd_print_stuff()
	except BrokenPipeError:
		pass
