import sys
from dharma import common, tei, tree, patch

def extract_text(root: tree.Node):
	buf = []
	extract_text_inner(root, buf)
	# If there is a <div> at the end, we will end up with two '\n'. Only
	# keep one.
	while buf and buf[-1] == "\n":
		buf.pop()
	buf.append("\n")
	return "".join(str(s) for s in buf)

def extract_text_from_tag(root, buf):
	match root.name:
		case "logical":
			for node in root:
				extract_text_inner(node, buf)
		case "para":
			for node in root:
				extract_text_inner(node, buf)
			buf.append("\n")
		case "npage" | "nline" | "ncell" | "display":
			pass
		case "span" | "search" | "link":
			for node in root:
				extract_text_inner(node, buf)
		case "split":
			node = root.first("search")
			assert node is not None
			extract_text_inner(node, buf)
		case "verse":
			extract_from_verse(root, buf)
		case "div" if common.to_boolean(root["phantom"]):
			pass
		case "div":
			head = root.first("stuck-child::head")
			for node in root:
				if node is head:
					continue
				extract_text_inner(node, buf)
			# This will add an excess newline at the end of the
			# file, so will need to be removed eventually.
			buf.append("\n")
		case "note":
			# We will have to do something sensible about it later
			# on.
			# Pour rendre cherchables les notes, les placer à la
			# fin du document. Et considérer <note> comme une sorte
			# de division. On devrai également considérer l'élément
			# quote commee une div, et avoir des éléments para ou
			# verse dedans. Idem for list and dlist items.
			pass
		case "elist":
			extract_from_elist(root, buf)
		case "dlist":
			extract_from_dlist(root, buf)
		case "quote":
			source = root.first("stuck-child::source")
			buf.append("\t")
			for node in root:
				if node is source:
					continue
				extract_text_inner(node, buf)
		case _:
			raise Exception(f"unsupported: {root.name}")

def extract_from_elist(root, buf):
	labels = generate_list_labels(root)
	for label, item in zip(labels, root.find("item")):
		buf.append(label)
		buf.append(" ")
		for thing in item:
			extract_text_inner(thing, buf)

def extract_from_dlist(root, buf):
	keys = root.find("key")
	values = root.find("value")
	assert len(keys) == len(values)
	for key, value in zip(keys, values):
		tmp = []
		for thing in key:
			extract_text_inner(thing, tmp)
		while tmp and tmp[-1] == "\n":
			tmp.pop()
		buf.extend(tmp)
		buf.append("➤")
		tmp.clear()
		for thing in value:
			extract_text_inner(thing, tmp)
		while tmp and tmp[-1] == "\n":
			tmp.pop()
		buf.extend(tmp)
		buf.append("\n")

def extract_from_verse(root, buf):
	first = True
	for line in root.find("verse-line"):
		if first:
			first = False
		elif common.to_boolean(line["break"]):
			buf.append(" ")
		for child in line:
			extract_text_inner(child, buf)

def generate_list_labels(node):
	match node["type"]:
		case "plain":
			while True:
				yield "◦"
		case "bulleted":
			while True:
				yield "•"
		case "numbered":
			i = 0
			while True:
				i += 1
				yield f"{i}."
		case _:
			raise Exception(f"bad value: {node!r}")

def extract_text_inner(root, buf):
	match root:
		case tree.String():
			buf.append(translate_string(root))
		case tree.Tag():
			extract_text_from_tag(root, buf)
		case tree.Comment():
			pass
		case _:
			raise Exception(f"unexpected: {root!r}")

def translate_string(s):
	tmp = []
	for c in s.data:
		if c == '’':
			c = "’"
		tmp.append(c)
	return "".join(tmp)

def get_identifier(doc):
	ident = doc.first("/document/identifier")
	if ident:
		return ident.text()
	return ""

def get_logical(doc):
	logical = doc.first("/document/edition/logical")
	if not logical:
		return ""
	return extract_text(logical)

def prepare_search_data(doc):
	data = {}
	data["identifier"] = get_identifier(doc)
	data["logical"] = get_logical(doc)
	return data

def add_document(file):
	try:
		doc = tei.process_file(file).to_internal()
	except tree.Error:
		doc = tree.Tree()
		doc.append(tree.Tag("document"))
	# XXX the following should not depend on the document already being
	# inserted in the db.
	data = patch.fetch_file_data(file.name)
	patch.add_file_info(doc, data)
	data = prepare_search_data(doc)
	db = common.db("texts")
	db.execute("""
	insert or replace into documents_search(identifier, logical)
	values (:identifier, :logical)""", data)

def main():
	doc = tree.parse(sys.argv[1])
	ret = prepare_search_data(doc)
	sys.stdout.write(ret["logical"])
	# python search.py tmp.int

if __name__ == "__main__":
	main()
