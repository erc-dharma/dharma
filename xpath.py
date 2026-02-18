import argparse, sys
from dharma import common, tree, languages

# TODO
# in xpath maybe support yielding strings (only need this for the last component,
# for use in the command-line tool)
# allow selection of attrs in xpath, useful for doing searches from the cmd line


@common.transaction("texts")
def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("expression")
	parser.add_argument("file", nargs="*")
	args = parser.parse_args()
	f = tree.generator.compile(args.expression)
	if not args.file:
		sys.stdout.write(f.source_code)
		return
	for file in args.file:
		try:
			t = tree.parse(file)
		except tree.Error:
			continue
		for result in f(t):
			print(f"{tree.term_color('#9d40b4')}>>> {file}: {result.path}{tree.term_color()}")
			print(result.xml())
			sys.stdout.flush()

if __name__ == "__main__":
	try:
		main()
	except (KeyboardInterrupt, BrokenPipeError):
		exit(1)
