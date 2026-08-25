import sys, os, re, collections, unicodedata
from dharma import tree, common, ingest

ROOT = common.path_of("repos/south-indian-inscriptions/SII_A_raw/2mastercopy/volumes")
HANDLERS = []

def handler(path):
	def decorator(f):
		HANDLERS.append((tree.Node.match_func(path), f))
		return f
	return decorator

@handler("volume")
def render_volume(self, node):
	self.push("div", class_="sii-volume")
	self.dispatch_children(node)
	self.join()

@handler("inscription")
def render_inscription(self, node):
	self.push("div", class_="sii-inscription")
	ident = node["ident"]
	self.push("h2", class_="skip-toc", id=ident)
	self.bookmarks.append(ident)
	self.push("span", **{"class": "milestone", "data-tip": "Inscription identifier"})
	self.append(f"⟨{ident}⟩ ")
	self.join()
	if (head := node.first("stuck-child::head")):
		self.dispatch_children(head)
		self.visited.add(head)
	self.join()
	self.dispatch_children(node)
	self.join()

@handler("group")
@handler("edition")
@handler("translation")
@handler("ch") # apparently only used without contents; = char?
@handler("ta")
@handler("te")
@handler("ka")
@handler("lat")
@handler("arab")
@handler("malayalam")
@handler("greek")
@handler("skttr")
@handler("urdu")
@handler("arn")
@handler("eng")
@handler("unkntr")
@handler("brtr")
@handler("pers")
@handler("katr")
@handler("simtr")
@handler("de")
@handler("ce") # apparently editorial intervention within the text
@handler("dutch")
@handler("tetr")
@handler("pr")
@handler("tlka")
@handler("prtr")
@handler("detr")
@handler("table")
@handler("c1")
@handler("c2")
@handler("c3")
@handler("c4")
@handler("c5")
@handler("c6")
@handler("list")
def just_dispatch(self, node):
	self.dispatch_children(node)

@handler("g")
def render_g(self, node):
	text, is_placeholder, tip = ingest.make_gaiji(node)
	if is_placeholder:
		self.push("span", tip=tip, class_="symbol-placeholder")
		self.append(f"<{text}>")
		self.join()
	else:
		self.push("span", tip=tip, class_="symbol")
		self.append(text)
		self.join()

@handler("note")
def handle_note(self, node):
	self.push(tree.Tree())
	self.dispatch_children(node)
	tip = self.pop()
	self.push("span", **{"data-tip": tip.xml(), "class": "sup"})
	_, p, n = re.fullmatch(r"([1-9][0-9]*):([1-9][0-9]*)-(.+)", node["n"]).groups()
	self.append(n)
	self.join()

@handler("lb")
def just_ignore(self, node):
	pass

@handler("h1")
def render_h1(self, node):
	self.push(tree.Tree())
	for pb in node.find(".//pb"):
		self.visited.add(pb)
	self.dispatch_children(node)
	t = self.pop()
	assert self.title is None
	self.title = t

@handler("h2")
@handler("h3")
@handler("h4")
@handler("h5")
def render_heading_levels(self, node):
	self.push(node.name, class_="skip-toc")
	self.dispatch_children(node)
	self.join()

@handler("p")
def render_p(self, node):
	self.push(node.name)
	self.dispatch_children(node)
	self.join()

@handler("l")
def render_l(self, node):
	self.push("p", class_="line")
	self.push("span", class_="lb")
	self.push("span", **{"data-tip": "Line start"})
	_, _, _, n = re.fullmatch(r"([1-9][0-9]*):([1-9][0-9]*):([^:]+):(.+)", node["n"]).groups()
	self.append(f"⟨{n}⟩")
	self.join()
	self.append(" ")
	self.join()
	self.dispatch_children(node)
	self.join()

@handler("em")
@handler("i")
def render_italics(self, node):
	self.push("em")
	self.dispatch_children(node)
	self.join()

@handler("b")
def render_bold(self, node):
	self.push(node.name)
	self.dispatch_children(node)
	self.join()

@handler("pb")
def render_pb(self, node):
	self.push("span", class_="pagelike")
	self.push("span", **{"data-tip": "Page start"})
	page = int(node["n"].split(":")[1].split("-")[0])
	self.append(f"⟨Page {page}⟩")
	self.join()
	self.join()

@handler("gr")
def render_grantha(self, node):
	self.push("span", class_="grantha")
	self.dispatch_children(node)
	self.join()

@handler("*")
def render_tag(self, node):
	assert isinstance(node, tree.Tag)
	print(f"{__file__} UNKNOWN: {node.name}", file=sys.stderr)
	self.dispatch_children(node)

class Renderer(tree.Serializer):

	def __init__(self, input):
		super().__init__()
		self.handlers = HANDLERS
		self.input = input
		self.title = None
		self.bookmarks = []
		self.visited = set()

	def __call__(self):
		self.clear()
		self.push("div", class_="sii-volume")
		self.dispatch(self.input.root)
		self.join()
		return self.title, self.tree, self.bookmarks

	def dispatch(self, node):
		if node in self.visited:
			return
		match node:
			case tree.Comment() | tree.Instruction():
				return
			case tree.String() | str():
				self.append(node)
				return
			case tree.Tag() | tree.Tree():
				pass
			case _:
				raise Exception(f"unknown {node}")
		for matcher, f in self.handlers:
			if matcher(node):
				break
		else:
			raise Exception
		f(self, node)

	def dispatch_children(self, node):
		for child in node:
			self.dispatch(child)

def delete_lb_break_no(node):
	def starts_with_upper(r):
		r = r.data.lstrip()
		if len(r) == 0:
			return False
		return r[0].isupper()
	# dans les originaux -<lb break="no"/> virer et le tag et le - SAUF si majuscule après
	before = preceding_string(node)
	after = following_string(node)
	assert before and after
	if before.data.rstrip().endswith("-"):
		if not starts_with_upper(after):
			before.replace_with(before.data.rstrip()[:-1])
			after.replace_with(after.data.lstrip())
		node.delete()
	else:
		node.replace_with(" ")

def following(node):
	def inner(nodes):
		for node in nodes:
			yield node
			if isinstance(node, tree.Tag):
				yield from inner(node)
	while not isinstance(node, tree.Tree):
		parent = node.parent
		i = parent.index(node)
		yield from inner(parent[i + 1:])
		node = parent

def preceding(node):
	def inner(nodes):
		for node in reversed(nodes):
			yield node
			if isinstance(node, tree.Tag):
				yield from inner(node)
	while not isinstance(node, tree.Tree):
		parent = node.parent
		i = node.parent.index(node)
		yield from inner(parent[:i])
		node = parent

def preceding_string(node):
	for node in preceding(node):
		if isinstance(node, tree.String):
			return node

def following_string(node):
	for node in following(node):
		if isinstance(node, tree.String):
			return node

def process_volume(name):
	name = os.path.splitext(name)[0]
	path = common.path_of(ROOT, f"{name}.xml")
	try:
		t = tree.parse(path)
	except FileNotFoundError:
		return None, None
	# Replace X-<lb break="no"/>Y with XY
	for lb in t.find("//lb"):
		delete_lb_break_no(lb)
	# Add spaces around <pb>
	for pb in t.find("//pb"):
		pb.insert_before(" ")
		pb.insert_after(" ")
	annotate_with_numbers(t)
	render = Renderer(t)
	return render()

def annotate_with_numbers(t):
	for vol in t.find("volume"):
		print(vol)
		xs = vol["n"].split("-")
		vol_no = int(xs[0])
		if len(xs) == 1:
			part_no = 0
		else:
			part_no = int(xs[1])
			assert part_no > 0
		sections = vol.find(".//part")
		if sections:
			for section_no, node in enumerate(sections, 1):
				_process_section(node, vol_no, part_no, section_no)
		else:
			_process_section(vol, vol_no, part_no, 0)

def _process_section(root, vol_no, part_no, section_no):
	for ins in root.find(".//inscription"):
		ins_no = ins["n"].rsplit(":")[-1]
		ins_id = _inscription_id(vol_no, section_no, ins_no)
		ins["ident"] = ins_id
		lang, script_info = language_and_script_of(ins)
		if lang == "tel" or lang == "kan":
			for sn in strings(ins):
				s = sn.data
				s = s.replace("¨r", "r")
				s = s.replace("n®", "N")
				if sn.data != s:
					sn.replace_with(s)
		if (editions := ins.find("edition")):
			for edition in editions:
				fix_lines(edition)

def iter_strings(node, ignore_notes=False):
	match node:
		case tree.String():
			yield node
		case tree.Tag() if ignore_notes and node.name == "note":
			pass
		case tree.Tag() if node.name == "ce":
			pass
		case tree.Tag() | tree.Tree():
			for kid in node:
				yield from iter_strings(kid, ignore_notes=True)

def strings(node):
	return list(iter_strings(node))

def strings_in(root):
	for node in root:
		match node:
			case tree.String():
				yield node
			case tree.Tag():
				yield from strings_in(node)
			case _:
				pass

def fix_initials(node, initial):
	for sn in strings(node):
		i = 0
		s = sn.data
		while i < len(s):
			if initial and is_vowel(s[i]):
				s = s[:i] + s[i].upper() + s[i + 1:]
				initial = False
			elif initial and i + 1 < len(s) and s[i] == "\N{middle dot}" and is_vowel(s[i + 1]):
				s = s[:i] + s[i + 1].upper() + s[i + 2:]
				initial = False
			elif s[i] == " ":
				initial = True
			else:
				initial = False
			i += 1
		if sn.data != s:
			sn.replace_with(s)

def fix_lines(edition):
	brk = True
	for l in edition.find("l"):
		fix_initials(l, brk)
		ss = strings(l)
		brk = True
		while ss:
			s = ss.pop()
			if s.isspace():
				continue
			if s.data.rstrip().endswith("-"):
				brk = False
			break

def is_vowel(c):
	return unicodedata.normalize("NFD", c.lower())[0] in "aeiou"

def _inscription_id(vol_no, section_no, ins_no):
	if "-" in ins_no:
		s, e = ins_no.split("-")
		padded_ins_no = f"{pad_ins_num(s)}-{pad_ins_num(e)}"
	else:
		padded_ins_no = f"{pad_ins_num(ins_no)}"
	return f"SIIv{vol_no:02}p{section_no}i{padded_ins_no}"

def pad_ins_num(x):
	i = 0
	while i < len(x) and x[i].isdigit():
		i += 1
	num, letters = int(x[:i]), x[i:]
	return f"{num:04}{letters}"

def language_and_script_of(ins):
	ins = ins.copy()
	for ce in ins.find("//ce"):
		ce.delete()
	for note in ins.find("//note"):
		note.delete()
	langs_freqs = collections.defaultdict(int)
	langs_freqs[None] = -1
	scripts_freqs = collections.defaultdict(int)
	scripts_freqs[None] = -1
	for l in ins.find("//l"):
		for node in strings_in(l):
			length = sum(not c.isspace() for c in node.data)
			lang = script = None
			while not lang or not script:
				node = node.parent
				if node is l:
					break
				if not lang:
					lang = languages.get(node.name)
				if not script:
					script = scripts.get(node.name)
			langs_freqs[lang] += length
			scripts_freqs[script] += length
	lang = max(langs_freqs, key=lambda k: langs_freqs[k])
	if ins["lang"]:
		lang = ins["lang"]
		assert len(lang) == 3
	script = max(scripts_freqs, key=lambda k: scripts_freqs[k]) or (None, None)
	return lang, script

scripts = {
	"arab": ("arabic", None),
	"brtr": ("brāhmī", "late"), # Only one inscription
	"de": ("nāgarī", None),
	"detr": ("nāgarī", None),
	"dutch": ("latin", None),
	"eng": ("latin", None),
	"gr": ("grantha", "vernacular"),
	"greek": ("greek", None),
	"ka": ("kannada", None),
	"katr": ("kannada", None),
	"lat": ("latin", None),
	"malayalam": ("malayalam", None),
	"pers": ("persian", None),
	"pr": ("brāhmī", None),
	"prtr": ("brāhmī", None),
	"simtr": ("siṃhala", None),
	"skttr": ("brāhmī", None), # Only one inscription
	"ta": ("tamil", "vernacular"),
	"te": ("telugu", "vernacular"),
	"tetr": ("telugu", "vernacular"),
	"urdu": ("urdu", None),
}

languages = {
	"arab": "ara",
	"brtr": None,
	"de": None,
	"detr": None,
	"dutch": "nld",
	"eng": "eng",
	"gr": None,
	"greek": "grk",
	"ka": "kan",
	"katr": "kan",
	"lat": "lat",
	"malayalam": "mal",
	"pers": "per",
	"pr": "pra",
	"prtr": "pra",
	"simtr": "sin",
	"skttr": "san",
	"ta": "tam",
	"te": "tel",
	"tetr": "tel",
	"urdu": "urd",
}

scripts_ignore = {}
for tag, infos in scripts.items():
	scripts_ignore.setdefault(infos, set()).add(tag)

def enumerate_volumes():
	volumes = []
	for name in sorted(os.listdir(ROOT)):
		volume, part = re.fullmatch(r"0*([0-9]+)(?:-0*([0-9]+))?\.xml", name).groups()
		volume = int(volume)
		part = part and int(part) or 0
		path = os.path.splitext(name)[0]
		volumes.append((volume, part, path))
	return volumes
