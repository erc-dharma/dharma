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

# This should be applied everywhere, whatever the field.
main = {
	"\N{RIGHT SINGLE QUOTATION MARK}": "'",
	"œ": "oe",
	"æ": "ae",
	"đ": "d",
}

# Some of the transformations described below are performed only to ensure that
# a symbol is represented with a single code point in the search representation.
# This is the case for digraphs (ai, au, etc.) and for composed characters that
# do not have precomposed equivalents (r̥, r̥̄, etc.). For search, we don't want
# to have to perform a lookahead on each match to test whether a combining char
# follows. When segmenting the text, we should still try not to cut it before a
# combining char.
edition = {
	# Apparently, the underscore should be treated as a space character.
	"_": " ",
	# In Tamil, the character "'" represents an elided "u" when it appears
	# at the end of a word, thus:
	#
	#     kaṇṇāṟṟ’ iraṇṭāñ
	#     uttirōttar’-abhivriddhi
	#
	# But when "'" appears at the beginning of a word, it represents the
	# avagraha, thus:
	#
	#     durvvāso-’nukāribhyaḥ
	#     bar ’nukāribhyaḥ
	#     sthirayogo’pi # not supposed to happen, but does happen.
	#     ’!pi # = 'pi
	#
	# We will resolve the ambiguity later on. The rule should be: if the
	# next character is null, is a space, or is a hyphen, treat it as a "u",
	# otherwise as an "a".
	"'": a_or_u,
	"’": a_or_u,
	# The following two always represent the avagraha.
	"'!": "a",
	"’!": "a",
	# Hyphens signal the beginning/end of a word, like spaces. We might use
	# this info for other purposes.
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
	# These are equivalent.
	"ă": "a",
	"ĕ": "e",
	"ĭ": "i",
	"ŏ": "o",
	"ŭ": "u",
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
	"\N{LATIN SMALL LETTER SCHWA}\N{COMBINING MACRON}": long_schwa,
	"\N{LATIN CAPITAL LETTER SCHWA}\N{COMBINING MACRON}": Long_schwa,
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

"""
Arlo stuff:

[ "a", "ā" ],
[ "b", "bh" ],
[ "c", "ch" ],
[ "d", "dh", "ḍ", "ḍh" ],
[ "ə", "ə̄", "ə:" ],<!-- I have added the equivalence with "ə:" — I hope the use of the colon here is unproblematic -->
[ "e", "ai" ],
[ "g", "gh" ],
[ "h" ],
[ "i", "ī" ],
[ "j", "jh" ],
[ "k", "kh" ],
[ "l" ],
[ "m", "ḿ" ],
[ "n" ],
[ "ṅ", "ṁ" ],
[ "ñ" ],
[ "o" ],
[ "p", "ph" ],
[ "r", "r̥" ],<!--I don't really understand why the author that table included this equivalence; in practise, in diplomatically edited OJ texts, r̥ and l̥ are nrpmalized to what rə/ər and lə in critical editions -->
[ "s", "ś", "ṣ" ],
[ "t", "th", "ṭ", "ṭh" ],
[ "u", "ū" ],
[ "v", "w" ],
[ "y" ]
[ "h", "ḥ" ]

<!-- should the facts that capital letters A, I, U, E, Ai, O, Au in strict translteration are equivalent to their lower case versions in loos transliteration, and that R̥, L̥ are equivalent to r̥ or rə and to lə, respectively, also be expressed above?-->
"""
