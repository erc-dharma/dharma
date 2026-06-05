import logging, copy
from dharma import tree, texts, common, ingest, enrich

def delete(name):
	db = common.db("texts")
	db.execute("delete from documents where name = ?", (name,))

def copy_node_contents(node):
	assert isinstance(node, tree.Tag) or node is None
	if node is None or node.empty:
		return node
	node = node.copy()
	ret = node.tree
	node.unwrap()
	return ret

def make_document_record(doc: tree.Tree):
	rec = {}
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
		scripts = ["script_other"]
	rec["scripts"] = scripts
	editors_ids = []
	for node in doc.find("/document/editor/identifier"):
		editors_ids.append(node.text())
	rec["editors"] = editors_ids
	return rec

def insert(file: texts.File):
	# Process the file once and persist records into both catalog and search databases.
	db = common.db("texts")
	logging.info(f"processing {file!r}")
	doc, cat_data = _extract_catalog_data(file)
	_insert_catalog(db, cat_data)
	search_data = _extract_search_data(file, doc)
	_insert_search(db, search_data)

def _extract_catalog_data(file: texts.File):
	# Ingest the file and build the catalog record to avoid duplicate tree parsing.
	try:
		doc = ingest.process_file(file)
		enrich.process(doc)
		data = make_document_record(doc)
	except tree.Error:
		doc = tree.Tree()
		doc.append(tree.Tag("document"))
		data = {"langs": ["und"], "scripts": ["script_other"], "editors": []}
	data.update({"name": file.name, "repo": file.repo, "status": file.status})
	return doc, data

def _extract_search_data(file: texts.File, doc: tree.Tree):
	# Augment the parsed document with file info and prepare data for the search index.
	import search
	file_data = enrich.fetch_file_data(file.name)
	enrich.add_file_info(doc, file_data)
	search_data = search.prepare_search_data(doc)
	for field, config in search.SEARCH_CONFIG.items():
		if config["type"] in ["list", "people"]:
			search_data[field] = search_data.get(field) or []
	return search_data

def _insert_catalog(db, data):
	# Persist the extracted catalog metadata into the main documents table.
	db.execute("""
	insert or replace into documents(name, repo, editors, langs, status, scripts)
	values (:name, :repo, :editors, :langs, :status, :scripts)
	""", data)

def _insert_search(db, data):
	# Persist the search-specific data into the full-text search table.
	db.execute("""
	insert or replace into documents_search(
		ident, logical, title, summary, repo_id, repo_name, hand,
		author, editor, lang, script, source
	)
	values (
		:ident, :logical, :title, :summary, :repo_id, :repo_name, :hand,
		:author, :editor, :lang, :script, :source
	)
	""", data)

# Rebuild the full catalog with the data already present in the db, i.e. without
# fetching files from github repos but instead from the db. This should be used
# after modifications to the processing code.
def rebuild():
	logging.info("rebuilding the catalog")
	db = common.db("texts")
	for repo, path, mtime, data in db.execute("""
		select files.repo, path, mtime, data
		from files join documents on files.name = documents.name
		order by files.repo, files.name"""):
		insert(texts.File(repo, path, mtime=mtime, data=data))
	logging.info("rebuilded the catalog")
