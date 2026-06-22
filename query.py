import argparse, tokenize, traceback, difflib
from pegen.tokenizer import Tokenizer
from dharma import common, tree, query_parser

class InvalidQuery(Exception):

	pass

VALID_FIELDS = {
	"ident",
	"repo", "repo.ident", "repo.name",
	"title",
	"editor", "editor.ident", "editor.name",
	"author", "author.ident", "author.name",
	"summary",
	"hand",
	"translation",
	"bibliography",
	"logical",
	"lang", "lang.ident", "lang.name",
	"script", "script.ident", "script.name"
}

# Map shorthand aliases to their canonical field names to allow brief queries
FIELD_ALIASES = {
	"trans": "translation",
	"bibl": "bibliography"
}

# Maps internal database fields back to their dotted representation
REVERSE_MAPPING = {
	"repo_id": "repo.ident",
	"repo_name": "repo.name",
	"editor_ident": "editor.ident",
	"editor_name": "editor.name",
	"author_ident": "author.ident",
	"author_name": "author.name",
	"lang_ident": "lang.ident",
	"lang_name": "lang.name",
	"script_ident": "script.ident",
	"script_name": "script.name"
}

# Add slash character to split operators correctly
char_token = "():=[]"

def make_token(s, t):
	# Assign OP type to delimiters, NUMBER to digits, and NAME to text
	if t in char_token:
		tok_type = tokenize.OP
	elif t.isdigit():
		tok_type = tokenize.NUMBER
	else:
		tok_type = tokenize.NAME
	token = tokenize.TokenInfo(type=tok_type, string=t,
		start=(1, 0), end=(1, 0), line=s)
	return token

def read_string(s, i):
	# Parse a string literal enclosed in double quotes
	j = i
	while j < len(s):
		if s[j] == '"':
			break
		j += 1
	else:
		raise InvalidQuery("non-matching double quotes")
	return j

def tokenize_query(s):
	# Yield recognized tokens iteratively from the input string
	i = 0
	while i < len(s):
		if s[i].isspace():
			i += 1
			continue
		if s[i] in char_token:
			yield make_token(s, s[i])
			i += 1
			continue
		if s[i] == '"':
			j = read_string(s, i + 1)
			yield make_token(s, s[i + 1:j])
			i = j + 1
			continue
		j = i + 1
		while j < len(s):
			if s[j] in char_token or s[j].isspace():
				break
			j += 1
		yield make_token(s, s[i:j])
		i = j
	yield tokenize.TokenInfo(type=tokenize.ENDMARKER, string="",
		start=(1, 0), end=(1, 0), line="")

def check_field_validity(node, valid_fields):
	# Traverse the syntax tree recursively to ensure all fields exist and resolve aliases
	# Raise an InvalidQuery with spelling suggestions if needed
	if isinstance(node, query_parser.Field) and node.name:
		if node.name in FIELD_ALIASES:
			node.name = FIELD_ALIASES[node.name]
		orig_name = REVERSE_MAPPING.get(node.name, node.name)
		if orig_name not in valid_fields:
			matches = difflib.get_close_matches(orig_name, list(valid_fields) + list(FIELD_ALIASES), n=1)
			if matches:
				raise InvalidQuery(f"Unknown search field: '{orig_name}'. Did you mean '{matches[0]}'?")
			raise InvalidQuery(f"Unknown search field: '{orig_name}'")
	if hasattr(node, "children"):
		for child in node.children:
			check_field_validity(child, valid_fields)
	elif hasattr(node, "child") and node.child:
		check_field_validity(node.child, valid_fields)

def parse_query(expr, valid_fields=VALID_FIELDS):
	# Tokenize and parse the query string into a syntax tree
	# Catch internal errors and return readable English messages
	try:
		gen = tokenize_query(expr)
		tokenizer = Tokenizer(gen, verbose=False)
		parser = query_parser.GeneratedParser(tokenizer, verbose=False)
		root = parser.start()
	except (ValueError, tokenize.TokenError) as e:
		raise InvalidQuery(f"Invalid expression: {e}")
	if not root:
		err = parser.make_syntax_error("query expression")
		msg = "Syntax error" if getattr(err, 'text', None) else "Incomplete query"
		raise InvalidQuery(msg)
	if valid_fields is not None:
		check_field_validity(root, valid_fields)
	return root

if __name__ == "__main__":
	parser = argparse.ArgumentParser(description="Tests the query parser.")
	parser.add_argument("-t", "--tokenize", help="""tokenize the query
		instead of parsing it""", action="store_true")
	parser.add_argument("query")
	args = parser.parse_args()
	if args.tokenize:
		for tok in tokenize_query(args.query):
			print(tok)
	else:
		import json
		r = parse_query(args.query)
		print(json.dumps(r.serialize(), ensure_ascii=False, indent=4))
