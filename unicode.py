import sys, re, unicodedata, html
import icu # pip install PyICU

def graphemes(s):
	# ICU returns UTF-16 offsets, but we're working at the code point-level.
	itor = icu.BreakIterator.createCharacterInstance(icu.Locale())
	itor.setText(s)
	p, q, p16 = 0, 0, 0
	for q16 in itor:
		while p16 < q16:
			if ord(s[q]) > 0xffff:
				p16 += 1
				assert p16 < q16
			p16 += 1
			q += 1
		yield s[p:q]
		p = q

vowels = {
	"a", "e", "i", "o", "u",
	"\N{latin small letter schwa}",
	"ṃ", "ṁ", "m\N{combining candrabindu}",
	"ṛ", "ṝ", "ḷ", "ḹ",
	"r\N{combining ring below}", "r\N{combining ring below}\N{combining macron}",
	"l\N{combining ring below}", "l\N{combining ring below}\N{combining macron}",
	"ḥ"
}

# TODO reenable only for mobile+tablet or find a way to exclude soft hyphenate
# from clipboard copy, see https://stackoverflow.com/questions/28837944/simplest-way-to-filter-text-copied-from-a-web-page-using-javascript
# or use css for including the hyphen
# TODO try
"""
.hyphen::before {
  content: '\00AD';
}
and then
hel<span class=".hyphen"/>lo
# NO, the css solution does not work
# TODO: or just don't justify the text when it looks like it won't fit correctly
# (not enough spaces and hyphens), or maybe don't use justification at all.
"""
# def hyphenate(s):
# 	buf = ""
# 	brk = False
# 	for t in re.split(r"(\s+|-)", s):
# 		if t.isspace() or t == "-" or "\N{soft hyphen}" in t or len(t) <= 6:
# 			buf += t
# 			continue
# 		for g in graphemes(t):
# 			gn = unicodedata.normalize("NFD", g).casefold()
# 			if gn[0] in vowels:
# 				brk = True
# 				buf += g
# 			else:
# 				if brk:
# 					buf += "\N{soft hyphen}"
# 					brk = False
# 				buf += g
# 		buf = buf.rstrip("\N{soft hyphen}")
# 	return buf

def char_name(c):
	try:
		return unicodedata.name(c)
	except ValueError:
		return "U+%04X" % ord(c)

SCRIPTS = ("TAMIL", "TELUGU", "KHMER", "DEVANAGARI", "GRANTHA", "KANNADA", "BALINESE")

def script(g):
	# Not really correct, but enough for this purpose
	names = [char_name(c) for c in g]
	for s in SCRIPTS:
		if all(name.startswith(s + " ") for name in names):
			return s

valid_combinations = set("""
\N{LATIN SMALL LETTER R}\N{COMBINING RING BELOW}
\N{LATIN CAPITAL LETTER L}\N{COMBINING RING BELOW}
\N{LATIN CAPITAL LETTER R}\N{COMBINING RING BELOW}
\N{LATIN SMALL LETTER M}\N{COMBINING TILDE}
\N{LATIN SMALL LETTER SCHWA}\N{COMBINING MACRON}
\N{LATIN SMALL LETTER L}\N{COMBINING RING BELOW}
\N{LATIN SMALL LETTER M}\N{COMBINING CANDRABINDU}
\N{LATIN SMALL LETTER R}\N{COMBINING RING BELOW}\N{COMBINING MACRON}
\N{LATIN CAPITAL LETTER L}\N{COMBINING RING BELOW}\N{COMBINING MACRON}
\N{LATIN CAPITAL LETTER R}\N{COMBINING RING BELOW}\N{COMBINING MACRON}
\N{LATIN SMALL LETTER L}\N{COMBINING RING BELOW}\N{COMBINING MACRON}
\N{LATIN SMALL LETTER N}\N{COMBINING BREVE}
""".strip().splitlines())

def is_valid(g):
	if len(g) == 1:
		# Andrea always uses this for some reason
		if g[0] == "\N{CYRILLIC SMALL LETTER SCHWA}":
			return True
		return not char_name(g[0]).startswith("CYRILLIC ")
	return script(g) or g in valid_combinations

def validate(s):
	problems = []
	# We don't use str.splitlines() because it counts U+2028 and U+2029 as
	# line separators, while github, oxygen and normal text editors don't.
	s = unicodedata.normalize("NFC", s)
	lines = re.split(r"\r|\n|\r\n", s)
	for line_no, line in enumerate(lines, 1):
		gs = list(graphemes(line))
		for i, g in enumerate(gs):
			if is_valid(g):
				continue
			hl = html.escape("".join(gs[:i]))
			hl += "<mark>%s</mark>" % html.escape(g)
			hl += html.escape("".join(gs[i + 1:]))
			names = [char_name(c) for c in g]
			problem = {
				"line_no": line_no,
				"highlighted_line": hl,
				"grapheme": names,
			}
			problems.append(problem)
	return problems

if __name__ == "__main__":
	for line in sys.stdin:
		p = 0
		for g in graphemes(line):
			names = [char_name(c) for c in g]
			print(p, names)
			p += len(g)
