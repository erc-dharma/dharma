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
		scripts = ["script_other"]
	rec["scripts"] = scripts
	editors_ids = []
	for node in doc.find("/document/editor/identifier"):
		editors_ids.append(node.text())
	rec["editors"] = editors_ids
	rec["summary"] = copy_node_contents(doc.first("/document/summary"))
	return rec

def insert(file: texts.File):
	db = common.db("texts")
	logging.info(f"processing {file!r}")
	try:
		doc_tree = ingest.process_file(file)
		internal = copy.deepcopy(doc_tree)
		enrich.process(internal)
		data = make_document_record(file, internal)
		enrich.process(doc_tree)
	except tree.Error:
		data = {}
		data["langs"] = ["und"]
		data["scripts"] = ["script_other"]
		data["editors"] = []
		data["summary"] = None
	data["name"] = file.name
	data["repo"] = file.repo
	data["status"] = file.status
	db.execute("""
	insert or replace into documents(name, repo, editors,
		langs, status, scripts)
	values (:name, :repo, :editors, :langs, :status, :scripts)""", data)
	import search
	search.add_document(file)

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
