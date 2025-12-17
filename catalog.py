import logging
from dharma import tree, texts, common, tei, internal2html

class Query:

	def __init__(self, query, field=""):
		self.query = query
		self.field = field

	def __str__(self):
		if isinstance(self.query, str):
			ret = '"%s"' % self.query.replace('"', '""')
		else:
			ret = str(self.query)
		if self.field:
			ret = "%s:%s" % (self.field, ret)
		return ret

class AND(Query):

	def __init__(self, clauses):
		self.clauses = clauses

	def __str__(self):
		return "(%s)" % " AND ".join(str(clause) for clause in self.clauses)

class OR(Query):

	def __init__(self, clauses):
		self.clauses = clauses

	def __str__(self):
		return "(%s)" % " OR ".join(str(clause) for clause in self.clauses)

def delete(name):
	db = common.db("texts")
	db.execute("delete from documents_index where name = ?", (name,))
	db.execute("delete from documents where name = ?", (name,))

def copy_node_contents(node):
	assert isinstance(node, tree.Tag) or node is None
	if node is None or node.empty:
		return node
	node = node.copy()
	ret = node.tree
	node.unwrap()
	return ret

def make_document_record(file, doc: tree.Tree):
	rec = {}
	rec["title"] = copy_node_contents(doc.first("/document/title"))
	authors = []
	for node in doc.find("/document/author"):
		authors.append(node.text())
	rec["authors"] = authors
	langs = []
	for node in doc.find("/document/languages/language/identifier"):
		langs.append(node.text())
	if not langs:
		langs = ["und"]
	rec["langs"] = langs
	scripts = []
	for node in doc.find("/document/scripts/script/identifier"):
		scripts.append(node.text())
	if not scripts:
		scripts = ["source_other"]
	rec["scripts"] = scripts
	editors = []
	for node in doc.find("/document/editor/name"):
		editors.append(node.text())
	rec["editors"] = editors
	editors_ids = []
	for node in doc.find("/document/editor/identifier"):
		editors_ids.append(node.text())
	rec["editors_ids"] = editors_ids
	rec["summary"] = copy_node_contents(doc.first("/document/summary"))
	return rec

def make_indexed_record(data):
	rec = {}
	rec["name"] = data["name"]
	rec["ident"] = common.normalize_text(data["name"])
	if (repo := data.get("repo")):
		rec["repo"]= common.normalize_text(repo)
	else:
		rec["repo"] = None
	if (title := data.get("title")):
		rec["title"] = common.normalize_text(title.text())
	else:
		rec["title"] = None
	if (authors := data.get("authors")):
		rec["author"] = common.normalize_text("|".join(authors))
	else:
		rec["author"] = None
	if (editors := data.get("editors")):
		rec["editor"] = common.normalize_text("|".join(editors))
	else:
		rec["editor"] = None
	if (editors_ids := data.get("editors_ids")):
		rec["editor_id"] = common.normalize_text("|".join(editors_ids))
	else:
		rec["editor_id"] = None
	if (langs := data.get("langs")):
		rec["lang"] = common.normalize_text("|".join(langs))
	else:
		rec["lang"] = None
	if (scripts := data.get("scripts")):
		rec["script"] = common.normalize_text("|".join(scripts))
	else:
		rec["script"] = None
	if (summary := data.get("summary")):
		rec["summary"] = common.normalize_text(summary.text())
	else:
		rec["summary"] = None
	return rec

def make_search_record(t):
	return {}

def insert(file: texts.File):
	db = common.db("texts")
	logging.info(f"processing {file!r}")
	# XXX should store XML fields as such in the DB, not as HTML, because
	# we need to be able to highlight them later on.
	try:
		doc = tei.process_file(file)
		internal = doc.to_internal()
		data = make_document_record(file, internal)
		data["search"] = make_search_record(internal)
		html_doc = doc.to_html()
	except tree.Error:
		data = {}
		data["title"] = None
		data["authors"] = []
		data["langs"] = ["und"]
		data["scripts"] = ["source_other"]
		data["editors"] = []
		data["editors_ids"] = []
		data["summary"] = None
		data["search"] = {}
		html_doc = internal2html.HTMLDocument()
	data["name"] = file.name
	data["repo"] = file.repo
	data["status"] = file.status
	indexed = make_indexed_record(data)
	if html_doc and html_doc.titles:
		data["title"] = html_doc.titles[0].html()
	if html_doc and html_doc.summary:
		data["summary"] = html_doc.summary.html()
	db.execute("""
	insert or replace into documents(name, repo, title, authors, editors,
		editors_ids, langs, summary, status, scripts)
	values (:name, :repo, :title, :authors, :editors, :editors_ids, :langs,
	    	:summary, :status, :scripts)""", data)
	# We cannot have a primary key on documents_index (because fts virtual
	# tables do not support this), so we cannot use "insert or replace" and
	# must instead do a delete followed by an insert.
	db.execute("delete from documents_index where name = ?", (file.name,))
	db.execute("""
	insert into documents_index(name, ident, repo, title, author, editor,
		editor_id, lang, summary, script)
	values (:name, :ident, :repo, :title, :author, :editor,
		:editor_id, :lang, :summary, :script)""", indexed)

# Rebuild the full catalog with the data already present in the db, i.e. without
# fetching files from github repos but instead from the db. This should be used
# after modifications to the processing code.
def rebuild():
	logging.info("rebuilding the catalog")
	db = common.db("texts")
	db.execute("delete from documents_index")
	for repo, path, mtime, data in db.execute("""
		select files.repo, path, mtime, data
		from files join documents on files.name = documents.name
		order by files.repo, files.name"""):
		file = texts.File(repo, path)
		setattr(file, "_mtime", mtime)
		setattr(file, "_data", data)
		insert(file)
	logging.info("rebuilded the catalog")

class InvalidQuery(Exception):
	pass

def tokenize_query(q):
	toks = []
	i = 0
	while i < len(q):
		c = q[i]
		if c == ":":
			# Separator between field name and field contents,
			# e.g. title:hello
			toks.append(c)
			i += 1
		elif c == '"':
			# Quoted string. A backslash (\) can be used to escape
			# the " char itself and a backslash.
			i += 1
			tok = ""
			while i < len(q) and q[i] != '"':
				if q[i] == "\\":
					i += 1
					if i == len(q):
						raise InvalidQuery
				tok += q[i]
				i += 1
			if i == len(q):
				raise InvalidQuery
			toks.append(tok)
			i += 1
		elif c.isspace():
			# Split tokens on whitespace.
			i += 1
		else:
			i += 1
			tok = c
			while i < len(q) and q[i] not in ": ":
				if q[i] == "\\":
					i += 1
					if i == len(q):
						raise InvalidQuery
				tok += q[i]
				i += 1
			toks.append(tok)
	return toks

search_fields = {
	"ident", "repo", "title", "author",
	"editor", "editor_id", "summary", "lang",
}

def parse_query(q):
	toks = tokenize_query(q)
	i = 0
	clauses = []
	while i < len(toks):
		if toks[i] == ":":
			raise InvalidQuery
		elif i + 1 < len(toks) and toks[i + 1] == ":":
			field = toks[i]
			if i + 2 < len(toks) and toks[i + 2] != ":":
				clauses.append(Query(toks[i + 2], field))
			i += 3
		else:
			clauses.append(Query(toks[i]))
			i += 1
	return AND(clauses)

def patch_languages(q):
	db = common.db("texts")
	for clause in q.clauses:
		if clause.field != "lang":
			continue
		text = clause.query
		assert isinstance(text, str)
		if len(text) <= 3:
			(text,) = db.execute("select ifnull((select id from langs_by_code where code = ?), '')", (text,)).fetchone()
			clause.query = text
			continue
		langs = [Query(lang) for (lang,) in db.execute("select id from langs_by_name where name match ?", (text,))]
		if langs:
			clause.query = OR(langs)
		else:
			clause.query = "" # prevent matching

def construct_query(q):
	q = " ".join(common.normalize_text(t) for t in q.split()
		if t not in ("AND", "OR", "NOT"))
	if q:
		q = parse_query(q)
		patch_languages(q)
		return str(q)

# Number of catalog entries per page for the display at /texts
PER_PAGE = 50

@common.transaction("texts")
def search(q, sort, page):
	db = common.db("texts")
	q = construct_query(q)
	if q:
		(total,) = db.execute("""select count(*) from documents_index
			where documents_index match ?""", (q,)).fetchone()
	else:
		(total,) = db.execute("select count(*) from documents_index").fetchone()
	sql = """
		select documents.name, documents.repo, documents.title,
			documents.authors, documents.editors, json_group_array(distinct langs_list.name) as langs, documents.summary,
			repos.title as repo_title
		from documents
			join documents_index on documents.name = documents_index.name
			join repos on documents.repo = repos.repo
			join json_each(documents.langs)
			left join langs_by_code on langs_by_code.code = json_each.value
			left join langs_list on langs_list.id = langs_by_code.id
	"""
	if q:
		sql += " where documents_index match ?"
	match sort:
		case "ident":
			sort = "name"
		case "title" | "repo":
			pass
		case _:
			sort = "title"
	match sort:
		case "title":
			collation = "html_icu"
		case _:
			collation = "icu"
	sql += f"""
		group by documents.name order by documents.{sort} collate {collation} nulls last
		limit ? offset ?"""
	offset = (page - 1) * PER_PAGE
	limit = PER_PAGE
	if q:
		ret = db.execute(sql, (q, limit, offset)).fetchall()
	else:
		ret = db.execute(sql, (limit, offset)).fetchall()
	(last_updated,) = db.execute("""
		select cast(value as int)
		from metadata where key = 'last_updated'""").fetchone()
	return ret, total, PER_PAGE, last_updated
