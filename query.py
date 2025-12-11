"""Query tokenizer and parser.

The parsing grammar is in query_parser.g.
"""

import argparse, tokenize, traceback
from pegen.tokenizer import Tokenizer
from dharma.query_parser import GeneratedParser, And, Or, Not, Field, Null

class InvalidQuery(Exception):
	pass

def make_token(s, t):
	# For now we don't bother to indicate correct offsets. And we also
	# don't bother to distinguish operators, strings, etc. as python does,
	# because it doesn't matter for us.
	# (type, string, start, end, line)
	# start and end are tuples (line_no, col_no)
	token = tokenize.TokenInfo(type=tokenize.NAME, string=t,
		start=(1, 0), end=(1, 0), line=s)
	return token

def read_string(s, i):
	j = i
	while j < len(s):
		if s[j] == '"':
			break
		j += 1
	else:
		raise InvalidQuery("non-matching double quotes")
	return j

char_token = "():="

def tokenize_query(s):
	i = 0
	while i < len(s):
		if s[i].isspace():
			i += 1
			continue
		if s[i] in char_token:
			yield make_token(s,s[i])
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
	gen = tokenize_query(expr)
	tokenizer = Tokenizer(gen, verbose=False)
	parser = GeneratedParser(tokenizer, verbose=False)
	root = parser.start()
	if not root:
		err = parser.make_syntax_error("<query expression>")
		traceback.print_exception(err.__class__, err, None)
		raise err
	return root

if __name__ == "__main__":
	parser = argparse.ArgumentParser(description="Tests the query parser.")
	parser.add_argument("-t", "--tokenize", help="""tokenize the query,
		instead of parsing it""", action="store_true")
	parser.add_argument("query")
	args = parser.parse_args()
	if args.tokenize:
		for tok in tokenize_query(args.query):
			print(tok)
	else:
		r = parse_query(args.query)
		print(r)
