import argparse, tokenize, traceback
from pegen.tokenizer import Tokenizer
from dharma import common, tree, query_parser

class InvalidQuery(Exception):

	pass

# Add slash character to split operators correctly
char_token = "():=[]/"

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

def parse_query(expr):
	# Tokenize and parse the query string into a syntax tree
	gen = tokenize_query(expr)
	tokenizer = Tokenizer(gen, verbose=False)
	parser = query_parser.GeneratedParser(tokenizer, verbose=False)
	root = parser.start()
	if not root:
		err = parser.make_syntax_error("<query expression>")
		traceback.print_exception(err.__class__, err, None)
		raise err
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
