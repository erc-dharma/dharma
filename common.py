from __future__ import annotations
import os, sys, logging, json, subprocess, re, threading, warnings
import functools, unicodedata, collections.abc
from urllib.parse import quote
import icu # pip install PyICU
import apsw, apsw.ext # pip install apsw
import requests # pip install requests
import bs4

# Forward sqlite logs to the logging python module.
apsw.ext.log_sqlite()

warnings.filterwarnings("ignore", category=bs4.MarkupResemblesLocatorWarning,
	module="bs4")

DHARMA_HOME = os.path.dirname(os.path.abspath(__file__))
os.environ["DHARMA_HOME"] = DHARMA_HOME # for subprocesses

def path_of(*path_elems):
	return os.path.join(DHARMA_HOME, *path_elems)

logging.basicConfig(level="INFO")

# Like the eponymous function in xslt
def normalize_space(s):
	s = s.strip()
	return re.sub(r"\s+", " ", s)

# Turns some object (strings, list of strings or None) into a searchable string.
def normalize_text(s):
	if s is None:
		s = ""
	elif not isinstance(s, str):
		# Make sure matching doesn't work across array elements.
		s = "!!!!!".join(s)
	s = unicodedata.normalize("NFKD", s)
	s = "".join(c for c in s if not unicodedata.combining(c))
	s = s.casefold()
	s = s.replace("œ", "oe").replace("æ", "ae").replace("đ", "d")
	return unicodedata.normalize("NFC", s.strip())

# For seeing how different collations work, see:
# https://icu4c-demos.unicode.org/icu-bin/collation.html
COLLATOR = icu.Collator.createInstance()
# The following is for ignoring punctuation
# The corresponding locale string for ucol_open() is 'en-u-ka-shifted'.
COLLATOR.setAttribute(icu.UCollAttribute.ALTERNATE_HANDLING, icu.UCollAttributeValue.SHIFTED)

def collate_icu(a, b):
	# HACK the problem is that we are sorting by json fields and that
	# we must handle null values
	if a is None or a == "[]":
		if b is None or b == "[]":
			return 0
		return 1
	if b is None or b == "[]":
		return -1
	return COLLATOR.compare(a, b)

def collate_html_icu(a, b):
	if a is None:
		if b is None:
			return 0
		return 1
	elif b is None:
		return -1
	a = bs4.BeautifulSoup(a, "html.parser").get_text()
	b = bs4.BeautifulSoup(b, "html.parser").get_text()
	return COLLATOR.compare(a, b)

def format_url(*args):
	if len(args) == 0:
		return ""
	ret = args[0]
	if len(args) > 1:
		ret = ret % args[1:]
	return quote(ret, safe="/:")

def trigrams(s):
	return (s[i:i + 3] for i in range(len(s) - 3 + 1))

def jaccard(*seqs):
	s1, s2 = seqs
	ngrams1 = set(trigrams(s1))
	ngrams2 = set(trigrams(s2))
	try:
		inter = len(ngrams1 & ngrams2)
		return inter / (len(ngrams1) + len(ngrams2) - inter)
	except ZeroDivisionError:
		return 0

class Database:

	def __init__(self, conn):
		self._conn = conn
		# _protected < 0: not in a transaction
		# _protected = 0: in a transaction, first level
		# _protected > 0: within a nested transaction
		self._protected = False

	def execute(self, sql, *args, **kwargs):
		# We should never do anything outside of an explicitly
		# opened transaction.
		assert self._protected
		assert self._conn.in_transaction or sql.startswith("begin")
		return self._conn.execute(sql, *args, **kwargs)

	def save_file(self, file):
		self.execute("""
			insert or replace into files(
				name, repo, path, mtime,
				last_modified_commit, last_modified, data)
			values(?, ?, ?, ?, ?, ?, ?)""",
			(file.name, file.repo, file.path, file.mtime, *file.last_modified, file.data))
		for git_name in file.owners:
			self.execute("""
				insert or ignore into owners(name, git_name)
				values(?, ?)""", (file.name, git_name))

	def load_file(self, name):
		row = self.execute("""
			select files.name as name,
				repo, path, mtime,
				last_modified_commit, last_modified, data,
				json_group_array(owners.git_name) as file_owners
			from files join owners on files.name = owners.name
			where files.name = ? group by owners.git_name""",
			(name,)).fetchone()
		if not name:
			raise Exception("not found")
		from dharma import texts #XXX circular import
		f = texts.File(row["repo"], row["path"])
		setattr(f, "_mtime", row["mtime"])
		setattr(f, "_last_modified", (row["last_modified_commit"], row["last_modified"]))
		setattr(f, "_data", row["data"])
		setattr(f, "_owners", json.loads(row["file_owners"]))
		return f

class Cursor(apsw.Cursor):

	def __init__(self, connection: apsw.Connection):
		super().__init__(connection)
		self.row_trace = Row

	def execute(self, statements: str,
		bindings: apsw.Bindings | None = None, *,
		can_cache: bool = True, prepare_flags: int = 0,
		explain: int = -1) -> apsw.Cursor:
		return super().execute(statements,
			self._wrap_bindings(bindings), can_cache=can_cache,
			prepare_flags=prepare_flags, explain=explain)

	def _wrap_bindings(self, bindings: apsw.Bindings | None) -> apsw.Bindings | None:
		if bindings is None:
			return None
		if isinstance(bindings, (dict, collections.abc.Mapping)):
			return {k: self._convert(bindings[k]) for k in bindings}
		return tuple(self._convert(v) for v in bindings)

	def _convert(self, value) -> apsw.SQLiteValue:
		match value:
			case None | int() | bytes() | str() | float():
				return value
			case dict() | list():
				return to_json(value)
			case _:
				raise TypeError(f"No adapter registered for type {type(value)}")

class Row:

	def __init__(self, cursor: apsw.Cursor, row: apsw.SQLiteValues):
		self._row = row
		# get_description() returns a list of (col_name, col_type).
		self._columns = cursor.get_description()

	def __repr__(self):
		buf = ["{"]
		first = True
		for i, (col_name, _) in enumerate(self._columns):
			if first:
				first = False
			else:
				buf.append(", ")
			buf.append(repr(col_name))
			buf.append(": ")
			buf.append(repr(self._convert(i)))
		buf.append("}")
		return "".join(buf)

	def _convert(self, i):
		data = self._row[i]
		_, col_type = self._columns[i]
		if not isinstance(col_type, str):
			return data
		match col_type.lower():
			case "json":
				return from_json(data)
			case "timestamp":
				return int(data)
			case _:
				return data

	def _column_name_to_index(self, name):
		for i, (key, _) in enumerate(self._columns):
			if key == name:
				return i
		return -1

	def __getitem__(self, key):
		if isinstance(key, int):
			return self._convert(key)
		column = self._column_name_to_index(key)
		if column < 0:
			raise KeyError(f"no column '{key}'")
		return self._convert(column)

	def __setitem__(self, key, value):
		if isinstance(self._row, tuple):
			self._row = list(self._row)
			self._columns = list(self._columns)
		column = self._column_name_to_index(key)
		if column < 0:
			assert isinstance(self._columns, list)
			self._columns.append((key, ""))
			self._row.append(value)
		else:
			self._row[column] = value

	def keys(self):
		return (col_name for col_name, _ in self._columns)

	def values(self):
		for i in range(len(self._row)):
			yield self._convert(i)

	def items(self):
		assert len(self._row) == len(self._columns)
		return zip(self.keys(), self.values())

def _read_only_db():
	name = os.path.basename(sys.argv[0])
	return name not in ("change.py", "repos.py", "languages.py",
		"prosody.py", "biblio.py")

# We can only have one transaction active per database object, so we allocate
# new database objects for each thread. In a given thread, there is no point
# allocating more than one database object, so we allocate just one, and create
# it on demand.
_DATABASES = threading.local()

# TODO use this instead:
# https://stackoverflow.com/questions/880530/can-modules-have-properties-the-same-way-that-objects-can
def db(name):
	ret = getattr(_DATABASES, name, None)
	if ret:
		return ret
	path = path_of("dbs", name + ".sqlite")
	conn = apsw.Connection(path)
	conn.create_scalar_function("format_url", format_url, numargs=-1, deterministic=True)
	conn.create_scalar_function("jaccard", jaccard, numargs=2, deterministic=True)
	conn.create_collation("icu", collate_icu)
	conn.create_collation("html_icu", collate_html_icu)
	conn.cursor_factory = Cursor
	if name == "texts":
		with open(path_of("schema.sql")) as f:
			sql = f.read()
		if _read_only_db():
			# Make sure we do not attempt to modify the database.
			# And only execute pragmas in the schema, not the
			# create table, etc. stuff.
			conn.execute("pragma query_only = true")
			for line in sql.splitlines():
				if line.lstrip().startswith("pragma "):
					conn.execute(line)
		else:
			conn.execute(sql).fetchall()
	ret = Database(conn)
	setattr(_DATABASES, name, ret)
	return ret

def transaction(db_name):
	"""We begin/end transactions around functions that are decorated with
	`@transaction`. We rollback transactions when an exception occurs and is
	not catched. Nesting transactions is not possible."""
	def decorator(f):
		@functools.wraps(f)
		def decorated(*args, **kwargs):
			d = db(db_name)
			assert not d._protected
			assert not d._conn.in_transaction
			d._protected = True
			d.execute("begin")
			try:
				ret = f(*args, **kwargs)
				d.execute("commit")
			except Exception:
				if d._conn.in_transaction:
					d.execute("rollback")
				raise
			finally:
				d._protected = False
			assert not d._conn.in_transaction
			return ret
		return decorated
	return decorator

def from_json(o):
	match o:
		case bytes():
			return json.loads(o.decode())
		case str():
			return json.loads(o)
		case _:
			return o

class JSONEncoder(json.JSONEncoder):

	def default(self, o):
		return str(o)

def to_json(obj):
	return json.dumps(obj, ensure_ascii=False, separators=(",", ":"),
		sort_keys=True, cls=JSONEncoder)

def append_unique(items, item):
	"In-place"
	if item in items:
		return
	items.append(item)
	return items

def unique(items):
	"In-place"
	seen = set()
	i = 0
	while i < len(items):
		if items[i] in seen:
			del items[i]
		else:
			seen.add(items[i])
			i += 1
	return items

def command(*cmd, **kwargs):
	logging.debug("run %s" % " ".join(cmd))
	kwargs.setdefault("capture_output", True)
	kwargs.setdefault("check", True)
	kwargs.setdefault("env", os.environ)
	ret = None
	try:
		ret = subprocess.run(cmd, encoding="UTF-8", **kwargs)
	except subprocess.CalledProcessError:
		if ret:
			logging.info(ret.stderr)
		raise
	return ret

def pandoc(text: str) -> str:
	"Markdown to HTML conversion."
	# Note that there is a pandoc python library. It probably only wraps the
	# pandoc binary, and we don't have complicated use cases for now, so we
	# don't use it.
	return command("pandoc", "--from=markdown", "--to=html", "--standalone", input=text).stdout

def fetch_tsv(file):
	"""Fetch a TSV file from some given source. `file` can be: a
	`texts.File` object, an absolute file path like `/foo/bar.tsv`, or an
	URL like `https://foo.com/bar.tsv`. Returns a list of rows, where each
	row is a `dict` mapping field names to field values in the given row.
	We assume the first row contains field names.

        TODO: Should also store a local copy of files we fetch from the web
        (e.g. the iso639 data), in a cache, within the same db. this cache would
        be written to only by change.py, when processing files.
	"""
	from dharma import texts
	if isinstance(file, texts.File):
		text = file.text
	elif file.startswith("/"):
		with open(file) as f:
			text = f.read()
	else:
		r = requests.get(file)
		r.raise_for_status()
		text = r.text
	lines = text.splitlines()
	fields = lines[0].split("\t")
	ret = []
	for line in lines[1:]:
		items = [x.strip() for x in line.split("\t")]
		# Fill with empty values in case lines were rstripped.
		while len(items) < len(fields):
			items.append("")
		if len(items) > len(fields):
			raise Exception("bad format")
		row = zip(fields, items)
		ret.append(dict(row))
	return ret

CODE_HASH, CODE_DATE = command("git", "-C", DHARMA_HOME, "show", "--no-patch", "--format=%H %at", "HEAD").stdout.strip().split()
CODE_DATE = int(CODE_DATE)

def numberize(s, n):
	# Late import to avoid loading this big file if not necessary.
	from dharma import english
	match n:
		case str() if n.isdigit():
			if n.isdigit():
				n = int(n)
			else:
				n = 0
		case int():
			assert n >= 0
		case _:
			n = len(n)
	if n == 1:
		return s
	chunks = s.rsplit(None, 1)
	if len(chunks) == 1:
		head, tail = "", chunks[0]
	else:
		head, tail = chunks
	w = tail.casefold()
	if w in english.S:
		return s + "s"
	elif w in english.ES:
		return s + "es"
	elif w in english.IES:
		return s[:-1] + "ies"
	elif w in english.IDENT:
		return s
	pl = english.REST.get(w)
	if not pl:
		logging.error(f"cannot numberize term {s!r}")
		return s
	return head + tail[:1] + pl[1:]

def sentence_case(s):
	if not s:
		return ""
	t = s.split(None, 1)
	t[0] = t[0].capitalize()
	return " ".join(t)

def from_boolean(obj):
	return obj and "true" or "false"

def to_boolean(s, dflt=None):
	match s.lower():
		case "true" | "yes" | "on" | "1":
			return True
		case "false" | "no" | "off" | "0":
			return False
		case _:
			return dflt
