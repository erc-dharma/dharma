from automata.fa.nfa import NFA
from automata.fa.dfa import DFA

"""
Deux approches différentes sont possibles: on peut soit générer à l'avance les
représentations de recherche que l'on va utiliser en transformant le texte de
plusieurs manières (avec re2c ou équivalent), ou bien ne pas transformer le
texte et construire une expression régulière qui sera évaluée au moment de la
recherche. La seconde approche est la plus souple, partons là-dessus.

Pour les transformations, que faire en python, et que faire en go? Les
transformations pour lesquelles on a besoin de connaître la langue seraient
peut-être plus commodes à faire en python, car on devrait autrement trouver un
moyen de passer la langue au code go, ce qui n'est pas pratique. En même temps,
il est plus rapide et plus facile de faire la transformation en go (avec re2c),
et il serait sans doute utile que le code go connaisse la langue des portions de
texte, pour permettre ensuite de filtrer les passages par langue. Si l'on permet
cela, il faut trouver une stratégie d'encodage pour encoder la langue.

The search code should take a finite-state automaton as input. Then have several
functions in this module that will take the automaton as argument and modify it
in some way. At the end, we minimize the automaton and convert it back to a
regular expression. And we send this regular expression to the go server.

Il peut valoir la peine de ne pas utiliser le module regexp pour la recherche.
Si on manipule déjà à l'avance l'automate, autant carrément le minimiser et
employer une petite boucle d'évaluation en go.

En fait, il y a plusieurs choses.

Problème avec les points (1) et (2) ci-dessous. En principe, ces transformations
ne devraient être appliquées que sur le texte source, viz. l'édition et aussi
les éléments <foreign>.

(1) Pour la représentation de recherche, au moment où on la génère, il faut
d'abord convertir les multigraphes en un seul code point. L'idée est de faire en
sorte qu'en cherchant "a", on ne trouve pas "ai" ou "au", et qu'en cherchant
"r", on ne trouve pas "r̥".

Quand on a affaire à de vrais multigraphes comme "ai" et "au", il faut un
pré-traitement, mais ça va créer des problèmes pour les segments de texte en
anglais, où on ne devrait pas avoir de digraphes. On peut soit fondre les
multigraphes en un seul caractère avant la recherche, soit conserver les
caractères multiples et ajouter un test supplémentaire au moment de la recherche
pour vérifier si le match se termine au milieu d'un multigraphe, auquel cas, il
faut le rejeter.

Pour les grapheme cluster, la librairie go regexp ne peut pas vérifier les
grapheme boundaries, donc on devrait faire un test après chaque match retourné,
c'est pas très commode.

Pour l'instant, je pense que le plus commode serait de transformer le texte
d'entrée de manière à éliminer les multigraphes, ça simplifiera le code de
recherche ultérieur. On peut aussi décider de convertir l'UTF-8 vers un encodage
qui n'est pas variable-length, pour la même raison. Dans les deux cas, il faut
éventuellement simplifier des séquences de grapheme clusters, en retirant des
signes diacritiques par exemple, quand on ne peut rien faire de mieux.

Partons du principe que l'on n'essaiera pas de gérer les multigraphes ou l'UTF-8
durant la recherche, pour simplifier la recherche.

Il va falloir convertir le texte vers un encodage qui ne soit pas
variable-length. On peut, soit encoder chaque caractère accentué, etc. en une
seule unité, soit encoder le caractère sur un octet et un bit mask sur le
suivant qui indique si le caractère porte un accent grave, etc. En fait, le plus
simple est de traiter chaque caractère séparément, sans bit mask, donc faisons
ça.

(2) Au moment où on génère la représentation de recherche, après avoir réalisé
les transformations (1), on devrait également appliquer les transformations qui
doivent toujours être appliquées, et qui devraient être:

(*) ignorer tous les caractères qui ne sont pas alphanumériques et qui ne sont
pas des espaces

(3) Ensuite, at search time, on applique les transformations qui doivent
demeurer optionnelles.

-- insensibilité à la casse -- ignorer les tirets -- ignorer les espaces

"""

# We store digraphs in the first private-use area. We start long after 0xE000
# because the go code uses the initial characters of this area for other
# purposes.
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
	# Apparently, the underscore should be treated as a space character.
	"_": " ",
}

# Some of the transformations described below are performed only to ensure that
# a symbol is represented with a single code point in the search representation.
# This is the case for digraphs (ai, au, etc.) and for composed characters that
# do not have precomposed equivalents (r̥, r̥̄, etc.). For search, we don't want
# to have to perform a lookahead on each match to test whether a combining char
# follows. When segmenting the text, we should still try not to cut it before a
# combining char.
#
# Spaces should be folded into one. And other non-alphabetic characters should
# be ignored (don't replace them with spaces, act if they didn't occur)
edition = {
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

class Automaton:

	def __init__(self):
		self.states = []
		self.start_state = self.add_state()

	def add_state(self):
		ret = State()
		self.states.append(ret)
		return ret

	@classmethod
	def from_string(cls, s):
		aut = Automaton()
		state = aut.start_state
		for c in s:
			next_state = aut.add_state()
			state.add_transition(c, next_state)
			state = next_state
		state.final = True
		return aut

class State:

	def __init__(self):
		self.transitions = {}
		self.final = False

	def add_transition(self, symbol, target):
		assert not symbol in self.transitions
		self.transitions[symbol] = target

def apply_table(aut, table):
	for state in aut.states:
		transitions = list(state.transitions.items())
		for symbol, target_state in transitions:
			match = table.get(symbol)
			if match is None:
				continue
			state.add_transition(match, target_state)

def two_ways(table):
	for k, v in list(table.items()):
		assert not v in table
		table[v] = k

# Treat voiced and unvoiced as equivalent.
voiced_unvoiced = two_ways({
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
})

# Treat aspirated and unaspirated as equivalent.
aspirated_unaspirated = two_ways({
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
})

# Treat retroflexes and dentals as equivalent.
retroflexes_dentals = two_ways({
	"ṭ": "t",
	ṭh: th,
	"ḍ": "d",
	ḍh: dh,
	"ṇ": "n",
})

# Treat sibilants as equivalent.
sibilants = two_ways({
	"ś": "s",
	"ṣ": "s",
})

# Treat long and short vowels as equivalent.
vowels = two_ways({
	"ā": "a",
	"ī": "i",
	"ū": "u",
	"ṝ": "ṛ",
	"ḹ": "ḷ",
	"ē": "e",
	"ō": "o",
})


# For details, see https://github.com/erc-dharma/project-documentation/issues/408#issue-3973658968.
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
