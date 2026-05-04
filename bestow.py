"""Display of BESTOW verses.

Main divisions are:

	translation
	inscriptions
	occurrences
	bibliography
	notes
	variation
"""

from dharma import common, tree, ingest, enrich, render

# Handlers are tested per order of appearance in this file, so the most
# specific ones should come first.
HANDLERS = []

def handler(path):
	def decorator(f):
		HANDLERS.append((tree.Node.match_func(path), f))
		return f
	return decorator

@handler("body/div/div[@type='translation']")
def handle_div_translation(self, div):
	self.push(tree.Tag("div"))
	self.push(tree.Tag("head"))
	self.append("Translation")
	resps = div["resp"]
	if resps:
		# If translators names are the exact same set of people
		# who edited the inscription, do not display them.
		resps = resps.split()
	if (sources := div["source"]):
		# Print in this order: bibliographic sources and names
		# of DHARMA members. Because we assume that, if both
		# are given, the DHARMA member is using an existing
		# traduction that he is trying to improve, so the
		# primary translator is the one mentioned in the
		# bibliography.
		self.append(" by ")
		finish_list = not resps
		ingest.append_sources(self, sources.split(), finish_list)
		if resps:
			self.append(", ")
			ingest.append_names(self, resps)
	elif resps:
		self.append(" by ")
		ingest.append_names(self, resps)
	self.join() # </head>
	self.dispatch_children(div)
	self.join() # </div>

@handler("body/div/div")
def handle_div(self, div):
	self.push(tree.Tag("div"))
	if div["type"] != "text":
		self.push(tree.Tag("head"))
		self.append(common.sentence_case(div["type"] or "???"))
		self.join() # </head>
	self.dispatch_children(div)
	self.join() # </div>

@handler("div/note")
def handle_note(self, note):
	self.push(tree.Tag("para"))
	self.dispatch_children(note)
	self.join()

@handler("body/div")
def handle_verse(self, div):
	self.push(tree.Tree())
	self.push(tree.Tag("div"))
	self.push(tree.Tag("head"))
	self.append(div["id"] or "???")
	self.join() # </head>
	self.dispatch_children(div)
	self.join() # </div>
	self.document.extra.append(self.pop())

HANDLERS.extend(ingest.HANDLERS)

def process():
	# XXX pull it from the db
	t = tree.parse("repos/BESTOW/DHARMA_BESTOW.xml")
	document_tree = ingest.process_tree(t, handlers=HANDLERS)
	return document_tree

if __name__ == "__main__":
	@common.transaction("texts")
	def main():
		t = tree.parse("repos/BESTOW/DHARMA_BESTOW.xml")
		document_tree = ingest.process_tree(t, handlers=HANDLERS)
		enrich.process(document_tree)
		html_doc = render.process(document_tree, toc_depth=1)
		print(html_doc)
	main()
