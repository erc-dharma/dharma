import os, sys, re
from dharma import common, tree, unicode, relaxng, xslt

# What should we use for representing error locations? Maybe just the patch the
# tree directly, since we're already doing that in python. But then must be able
# to address text nodes, etc.

# Validation levels
OK = 0		# No problem
WARNING = 1	# Possible Unicode issues
ERROR = 2	# Schema error
FATAL = 3	# Invalid XML, cannot be processed at all

# For simplifying RNG files, download rng2srng-20020831

# Nnote that we can link to a span of text on github by adding a fragment like
# #L8C23-L14C34 at the end; but doesn't work with just #L8C23.

def split_lines(text):
	return re.findall(r"(.*)(?:\r\n|\r|\n)", text)

class Message:

	def __init__(self):
		self.line: int = -1
		self.column: int = -1
		self.text: str | None = None
		self.assertion: str | None = None # schematron

	def __repr__(self):
		ret = f"{self.line}:{self.column}: {self.text}"
		if self.assertion:
			ret += f" {self.assertion}"
		return ret

class Result:

	def __init__(self):
		self.status = OK
		self.messages = []
		self.unicode = []

class Validator:

	def __init__(self, name, prefixes):
		self.name = name
		self.prefixes = prefixes
		self.sch_script = common.path_of("schemas", self.name + ".sch")
		path = common.path_of("schemas", self.name + ".rng")
		self.rng_schema = relaxng.Schema(path)

	# Here we don't care about error details, we just want to know the
	# error severity level, so this can be optimized further.
	def quick_check(self, file):
		try:
			tree.parse_string(file.data)
		except tree.Error:
			return FATAL
		if self.rng_schema(file.data):
			return ERROR
		if self.sch_error_nodes(file):
			return ERROR
		if self.uni_errors(file):
			return WARNING
		return OK

	def process(self, file):
		val = Result()
		try:
			xml = tree.parse_string(file.data)
		except tree.Error as e:
			val.status = FATAL
			m = Message()
			m.line = e.line
			m.column = e.column
			m.text = e.text
			val.messages.append(m)
			return val
		self.rng(file, val, xml)
		self.sch(file, val, xml)
		self.uni(file, val, xml)
		val.messages.sort(key=lambda x: (x.line, x.column))
		return val

	def rng(self, file, val, xml):
		errs = self.rng_schema(file.data)
		if not errs:
			return
		val.status = ERROR
		for err in errs:
			# for "more error messages follow but were truncated"
			# XXX find another way to signal that errors were truncated?
			if err.line < 0 and "were truncated" in err.text:
				continue
			m = Message()
			m.line = err.line
			m.column = err.column
			m.text = err.text
			val.messages.append(m)

	def sch_error_nodes(self, file):
		ret = xslt.transform(self.sch_script, file.text)
		rep = tree.parse_string(ret)
		return rep.find("//successful-report") + rep.find("//failed-assert")

	def sch(self, file, val, xml):
		errs = self.sch_error_nodes(file)
		if not errs:
			return
		val.status = ERROR
		for node in errs:
			loc = node["location"]
			loc = re.sub(r"/\*:([a-zA-Z]+)\[.+?\]\[([0-9]+)\]", r"/\1[\2]", loc)
			test = node["test"]
			msg = node.text()
			where = xml.locate(loc).location
			m = Message()
			m.line, m.column, m.text, m.assertion = where.line, where.column, msg, test
			val.messages.append(m)

	def uni_errors(self, file):
		return unicode.validate(file.text)

	def uni(self, file, val, xml):
		ret = self.uni_errors(file)
		if not ret:
			return
		if val.status < WARNING:
			val.status = WARNING
		val.unicode = ret

VALIDATORS = [
	Validator("inscription", ["DHARMA_INS"]),
	Validator("critical", ["DHARMA_DiplEd", "DHARMA_CritEd"])
]

def schema_from_filename(file):
	base = os.path.basename(file)
	for schema in VALIDATORS:
		for prefix in schema.prefixes:
			if base.startswith(prefix):
				return schema

def status(file):
	validator = schema_from_filename(file.name)
	if not validator:
		return -1 # XXX
	return validator.quick_check(file)

def file(file_obj):
	validator = schema_from_filename(file_obj.name)
	if not validator:
		return
	return validator.process(file_obj)

if __name__ == "__main__":
	from dharma import texts
	schema = Validator("inscription", "DHARMA_INS")
	for path in sys.argv[1:]:
		repo = os.path.dirname(os.path.relpath(os.path.abspath(path), common.path_of("repos")))
		child = os.path.relpath(os.path.abspath(path), common.path_of("repos", repo))
		f = texts.File(repo, child)
		ret = schema.process(f)
		print(path, ret.status)
		for m in ret.messages:
			print(f"{path}:{m}")
		print(schema.sch_error_nodes(f))
