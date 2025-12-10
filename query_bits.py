from dharma import common, tree

class Cursor:

	"Abstract class."

	def __init__(self):
		self.offset = -1

	def next(self) -> bool:
		return False

	def match(self) -> tuple[int, int]:
		raise NotImplementedError

	def seek(self, offset) -> bool:
		assert offset >= 0
		assert self.offset <= offset
		while self.offset < offset:
			self.next()
			if self.offset < 0:
				return False
		assert self.offset >= offset
		return True

class Substring(Cursor):

	def __init__(self, needle: str, source: str):
		assert len(needle) > 0
		self.needle = needle
		self.source = source
		self.offset = -len(self.needle)

	def next(self):
		if self.offset >= len(self.source):
			return False
		self.offset += len(self.needle)
		start = self.source.find(self.needle, self.offset)
		if start < 0:
			self.offset = len(self.source)
			return False
		self.offset = start
		return True

	def match(self):
		assert self.offset >= 0
		if self.offset >= len(self.source):
			return (-1, 0)
		return self.offset, len(self.needle)

class Tree(Cursor):

	def __init__(self, text: list[str], cursor: Cursor):
		self.transformer = Tokenizer(*text)
		self.start = -1
		self.length = 0
		self.cursor = cursor

	def next(self):
		if self.start == -2:
			return False
		while True:
			self.cursor.next()
			match_start, match_len = self.cursor.match()
			if match_start < 0:
				self.start = -2
				self.length = 0
				return False
			start, length = self.transformer.translate(match_start, match_len)
			if start >= 0:
				break
		self.start, self.length = start, length
		return True

	def match(self):
		return self.start, self.length

def normalize_char(c):
	c = c.casefold()
	match c:
		case "œ":
			return "oe"
		case "æ":
			return "ae"
		case "đ":
			return "d"
		case _:
			return c

def normalize_text(s):
	return "".join(normalize_char(c) for c in s)

class Tokenizer(Cursor):

	def __init__(self, *chunks):
		self.chunks = chunks
		self.chunk = 0
		self.chunk_offset = 0
		self.search_offset = 0
		self.display_offset = 0

	def try_next_chars(self) -> tuple[int, str]:
		assert self.chunk <= len(self.chunks)
		if self.chunk >= len(self.chunks):
			return 0, ""
		chunk = self.chunks[self.chunk]
		assert self.chunk_offset <= len(chunk)
		if self.chunk_offset >= len(chunk):
			self.chunk += 1
			self.chunk_offset = 0
			if self.chunk >= len(self.chunks):
				return 0, ""
			chunk = self.chunks[self.chunk]
		chars = normalize_char(chunk[self.chunk_offset])
		self.chunk_offset += 1
		return 1, chars

	def next_chars(self):
		ret = self.try_next_chars()
		if not ret:
			raise Exception
		return ret

	def translate(self, start, length) -> tuple[int, int]:
		"""After casefolding süße > süsse
		search "se": süs[se]; produce the interval sü[sse]
		search "üs": s[üs]se; produce the interval s[üss]e
		search "s": [s]ü[s][s]e; produce the intervals [s]ü[ss]e
		"""
		assert start >= 0 and length > 0
		dstart = -1
		dlength = 0
		if self.search_offset > start:
			if self.search_offset >= start + length:
				return -1, 0
			start = self.search_offset
		assert self.search_offset <= start
		while self.search_offset < start:
			n, cs = self.next_chars()
			if self.search_offset + len(cs) > start:
				dstart = self.display_offset
				self.display_offset += n
				self.search_offset += len(cs)
				if self.search_offset >= start + length:
					dlength = self.display_offset - dstart
					return dstart, dlength
				break
			else:
				self.display_offset += n
				self.search_offset += len(cs)
		else:
			dstart = self.display_offset
		assert self.search_offset >= start
		while self.search_offset < start + length:
			n, cs = self.next_chars()
			if self.search_offset + len(cs) > start + length:
				self.display_offset += n
				dlength = self.display_offset - dstart
				self.search_offset += len(cs)
				return dstart, dlength
			self.display_offset += n
			self.search_offset += len(cs)
		dlength = self.display_offset - dstart
		return dstart, dlength

def extract_text(root: tree.Node):
	buf = []
	extract_text_inner(root, buf)
	return buf

def extract_text_inner(root, buf):
	match root:
		case tree.String():
			buf.append(root)
			return
		case tree.Tree():
			for node in root:
				extract_text_inner(node, buf)
			return
		case tree.Tag():
			pass # See below.
		case _:
			return
	match root.name:
		case "logical" | "div" | "search" | "unclear":
			for node in root:
				extract_text_inner(node, buf)
		case "split":
			search = root.first("search")
			assert search is not None
			extract_text_inner(search, buf)
		# XXX won't work well for quote, list, dlist, can't recurse.
		case "para" | "verse" | "quote" | "elist" | "dlist":
			for node in root:
				extract_text_inner(node, buf)
			buf.append("\n")
		case "item" | "key" | "value":
			buf.append(" ")
			for node in root:
				extract_text_inner(node, buf)
		case "verse-line":
			if common.to_boolean(root["break"]):
				buf.append(" ")
			for node in root:
				extract_text_inner(node, buf)
		case "span" | "link":
			for node in root:
				extract_text_inner(node, buf)
		case "note" | "head" | "display" | "npage" | "nline" | "ncell":
			pass
		case _:
			raise Exception(f"unsupported: {root.name}")

class SearchableDocument:

	def __init__(self, tree):
		self.tree = tree

	def field(self, name):
		if name == "edition":
			return self.tree.first("/document/edition/logical")
		raise NotImplementedError

if __name__ == "__main__":
	import sys
	from dharma import tree
	t = tree.parse(sys.argv[1])
	doc = SearchableDocument(t)
	edition = doc.field("edition")
	text = extract_text(edition)
	print("".join(str(s) for s in text))
