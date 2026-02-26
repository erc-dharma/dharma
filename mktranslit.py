# For details, see https://github.com/erc-dharma/project-documentation/issues/408#issue-3973658968.

# We store digraphs in the first private-use area. We start long after 0xE000
# because the go code uses the initial characters of this area.
start = 0xE000 + 100
ai = chr(start + 0)
au = chr(start + 1)
kh = chr(start + 2)
gh = chr(start + 3)
ch = chr(start + 4)
jh = chr(start + 5)
ṭh = chr(start + 6)
ḍh = chr(start + 7)
th = chr(start + 8)
dh = chr(start + 9)
ph = chr(start + 10)
bh = chr(start + 11)
a_or_u = chr(start + 12)
long_schwa = chr(start + 13)
Long_schwa = chr(start + 14)

main = {
	"œ": "oe",
	"æ": "ae",
	"đ": "d",
}

# Some of the transformations described below are performed to ensure that a
# symbol is represented with a single code point. This is the case for digraphs
# (ai, au, etc.) and for composed characters that do not have precomposed
# equivalents (r̥, r̥̄, etc.). For search, we don't want to have to perform a
# lookahead on each match to test whether a combining char follows. When
# segmenting the text, we should still try not to cut it before a combining
# char.
edition = {
	# ":" is used between characters that form a digraph, as in pra:uga.
	# Just letting the lexer eat the character is enough, we don't
	# necessarily need to recognize a:i, a:u, etc.
	":": "",
	# Zero vowel marker (virāma), can be safely ignored.
	"·"
	# In Tamil, the character "'" represents an elided "u" when it appears
	# at the end of a word, thus:
	#
	#     kaṇṇāṟṟ’ iraṇṭāñ
	#     uttirōttar’-abhivriddhi
	#
	# But when it appears at the beginning of a word, it represents the
	# avagraha, thus:
	#
	#     durvvāso-’nukāribhyaḥ
	#     bar ’nukāribhyaḥ
	#     sthirayogo’pi # not supposed to happen, but does happen.
	#     ’!pi # = 'pi
	#
	# We will resolve the ambiguity later on. The rule should be: if the
	# next character is null, is a space, or is a hyphen, treat it as a "u",
	# otherwise as a "a".
	"'": a_or_u,
	"’": a_or_u,
	"'!": "a",
	"’!": "a",
	# Hyphens signal the beginning/end of a word, like spaces. We might use
	# this info for other purposes.
	"-": "",
	"¬": "",
	"■": "",
	"r̥": "ṛ",
	"r̥̄": "ṝ",
	"l̥": "ḷ",
	"l̥̄": "ḹ",
	# Anusvara and anunāsika, Cam anusvāra-candra
	"ṁ": "ṃ",
	"m̐": "ṃ",
	"m̃": "ṃ",
	# Upadhmānīya and jihvāmūlīya. Just fold them to a visarga.
	"ḫ": "ḥ",
	"ẖ": "ḥ",
	# Digraphs.
	"ai": ai,
	"au": au,
	"kh": kh,
	"gh": gh,
	"ch": ch,
	"jh": jh,
	"ṭh": ṭh,
	"ḍh": ḍh,
	"th": th,
	"dh": dh,
	"ph": ph,
	"bh": bh,
	# Javanese/Balinese pepet. Andrea always uses cyrillic letters for some
	# reason
	"\N{CYRILLIC SMALL LETTER SCHWA}": "ə",
	"\N{CYRILLIC SMALL LETTER SCHWA}\N{COMBINING MACRON}": long_schwa,
	"\N{CYRILLIC CAPITAL LETTER SCHWA}\N{COMBINING MACRON}": Long_schwa,
	"ə̄": long_schwa,
	"Ə̄": Long_schwa,
}

# Maps voiced to unvoiced.
voiced_unvoiced = {
	"g": "k",
	gh: kh,
	"j": "c",
	jh: ch,
	"ḍ": "ṭ",
	ḍh: ṭh,
	"d": "t",
	dh: th,
	"b": "p",
	bh: ph,
}

# Maps aspirated to unaspirated.
aspirated_unaspirated = {
	kh: "k",
	gh: "g",
	ch: "c",
	jh: "j",
	ṭh: "ṭ",
	ḍh: "ḍ",
	th: "t",
	dh: "d",
	ph: "p",
	bh: "b",
}

# Maps retroflexes to dentals.
retroflexes_dentals = {
	"ṭ": "t",
	"ṭh": "th",
	"ḍ": "d",
	"ḍh": "dh",
	"ṇ": "n",
}

# Merge sibilants.
sibilants = {
	"ś": "s",
	"ṣ": "s",
}

# Merge long and short vowels.
vowels = {
	"ā": "a",
	"ī": "i",
	"ū": "u",
	"ṝ": "ṛ",
	"ḹ": "ḷ",
	"ē": "e",
	"ō": "o",
}
