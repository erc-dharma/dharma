"""Display of BESTOW verses.

Main divisions are:

	translation
	inscriptions
	occurrences
	bibliography
	notes
	variation

TODO Dans <div type="notes">, remplacer les <note> par des <p>.
"""

from dharma import common, tree

# Handlers are tested per order of appearance in this file, so the most
# specific ones should come first.
HANDLERS = []

def handler(path):
	def decorator(f):
		HANDLERS.append((tree.Node.match_func(path), f))
		return f
	return decorator

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

import tei
HANDLERS.extend(tei.HANDLERS)

def process():
	t = tree.parse("repos/BESTOW/DHARMA_BESTOW.xml")
	document = tei.process_tree(t, handlers=HANDLERS)
	return document

if __name__ == "__main__":
	@common.transaction("texts")
	def main():
		t = tree.parse("repos/BESTOW/DHARMA_BESTOW.xml")
		document = tei.process_tree(t, handlers=HANDLERS)
		print(document.to_html(toc_depth=1))
	main()
