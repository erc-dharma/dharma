import argparse, tokenize, io, sys, traceback
from pegen.tokenizer import Tokenizer
from dharma.query_parser import GeneratedParser

# Like Python's tokenizer, but treats strings like "foo-bar-baz" as names, and
# also ignores newlines..
def tokenize_query(s):
	for tok in tokenize.generate_tokens(io.StringIO(s).readline):
		match tok.type:
			case tokenize.NEWLINE:
				pass
			case _:
				yield tok

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
	parser = argparse.ArgumentParser(description="""Test the query parser""")
	parser.add_argument("-t", "--tokenize", help="""tokenize the query,
		don't parse it""", action="store_true")
	parser.add_argument("query")
	args = parser.parse_args()
	if args.tokenize:
		for tok in tokenize_query(args.query):
			print(tok)
	else:
		r = parse_query(args.query)
		print(r)

