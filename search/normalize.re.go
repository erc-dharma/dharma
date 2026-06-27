//go:build ignore

package main

import (
	"log"
	"strings"
	"unicode"
	"unicode/utf8"

	"github.com/rivo/uniseg"
	"golang.org/x/text/cases"
)

// Dummy variables to prevent IDE formatters from stripping required imports.
var (
	_ = utf8.DecodeRuneInString
	_ = unicode.IsLetter
	_ = log.Fatalf
	_ = cases.Fold
)

var folder = cases.Fold()

const Pai = 0xE002
const Pau = 0xE003
const Pkh = 0xE004
const Pgh = 0xE005
const Pch = 0xE006
const Pjh = 0xE007
const P_th = 0xE008
const P_dh = 0xE009
const Pth = 0xE00A
const Pdh = 0xE00B
const Pph = 0xE00C
const Pbh = 0xE00D
const Plongschwa = 0xE00E

// peekByte safely reads a byte from a string to prevent out-of-bounds panics in re2c.
// It returns 0 when the cursor reaches or exceeds the string length.
func peekByte(s string, i int) byte {
	if i < len(s) {
		return s[i]
	}
	return 0
}

// lexPrefix uses a finite state machine to identify the next semantic sequence.
// It returns the byte length of the sequence, its string representation, and an elision flag.
// Updated to return string instead of rune for complex graphemes mapping.
func lexPrefix(text string) (int, string, bool) {
	cursor, marker := 0, 0
	_ = cursor
	_ = marker
	_ = text
	/*!re2c
	re2c:flags:8 = 1;
	re2c:yyfill:enable = 0;
	re2c:define:YYCTYPE = byte;
	re2c:define:YYPEEK = "peekByte(text, cursor)";
	re2c:define:YYSKIP = "cursor++";
	re2c:define:YYBACKUP = "marker = cursor";
	re2c:define:YYRESTORE = "cursor = marker";

	* { return 1, "", true }
	"æ" | "Æ" { return cursor, "ae", false }
	"œ" | "Œ" { return cursor, "oe", false }
	"đ" | "Đ" { return cursor, "d", false }

	// In Tamil, the character "'" represents an elided "u" when it appears
	// at the end of a word (viz. before a non-alphanumeric char or the
	// empty string), as in:
	//
	//     kaṇṇāṟṟ’ iraṇṭāñ
	//     uttirōttar’-abhivriddhi
	//
	// But when "'" appears at the beginning of a word (viz. immediately
	// before an alphabetic char), it represents the avagraha, even in
	// Tamil, as in:
	//
	//     durvvāso-’nukāribhyaḥ
	//     bar ’nukāribhyaḥ
	//     sthirayogo’pi # not supposed to happen, but does happen.
	//
	// Ideally, we should resolve the ambiguity, and transform the "'" into
	// an "a" or an "u". But for now, for simplicity, we just turn this
	// character into an "a".
	//
	// The sequences "'!" and "’!" always represent the avagraha, e.g.
	// ’!pi = 'pi = api
	"a" | "A" | "ă" | "Ă" | "'" | "’" | "'!" | "’!" { return cursor, "a", false }
	"ā" | "Ā" { return cursor, "ā", false }
	"i" | "I" | "ĭ" | "Ĭ" { return cursor, "i", false }
	"ī" | "Ī" { return cursor, "ī", false }
	"u" | "U" | "ŭ" | "Ŭ" { return cursor, "u", false }
	"ū" | "Ū" { return cursor, "ū", false }
	"ṛ" | "Ṛ" | "r̥" | "R̥" { return cursor, "ṛ", false }
	"ṝ" | "Ṝ" | "r̥̄" | "R̥̄" { return cursor, "ṝ", false }
	"ḷ" | "Ḷ" | "l̥" | "L̥"{ return cursor, "ḷ", false }
	"ḹ" | "Ḹ" | "l̥̄" | "L̥̄" { return cursor, "ḹ", false }
	"e" | "E" | "ĕ" | "Ĕ" | "ē" | "Ē" { return cursor, "e", false }
	"ai" | "Ai" | "AI" | "aI" { return cursor, string(rune(Pai)), false }
	"o" | "O" | "ŏ" | "Ŏ" | "ō" | "Ō" { return cursor, "o", false }
	"au" | "Au" | "AU" | "aU" { return cursor, string(rune(Pau)), false }
	"ṁ" | "Ṁ" | "ṃ" | "Ṃ" | "m̐" | "M̐" | "m̃" | "M̃" { return cursor, "ṃ", false }
	"ḥ" | "Ḥ" | "ḫ" | "Ḫ" | "ẖ" | "H̱" { return cursor, "ḥ", false }
	"k" | "K" { return cursor, "k", false }
	"kh" | "Kh" | "KH" | "kH" { return cursor, string(rune(Pkh)), false }
	"g" | "G" { return cursor, "g", false }
	"gh" | "Gh" | "GH" | "gH" { return cursor, string(rune(Pgh)), false }
	"ṅ" | "Ṅ" { return cursor, "ṅ", false }
	"c" | "C" { return cursor, "c", false }
	"ch" | "Ch" | "CH" | "cH" { return cursor, string(rune(Pch)), false }
	"j" | "J" { return cursor, "j", false }
	"jh" | "Jh" | "JH" | "jH" { return cursor, string(rune(Pjh)), false }
	"ñ" | "Ñ" { return cursor, "ñ", false }
	"ṭ" | "Ṭ" { return cursor, "ṭ", false }
	"ṭh" | "Ṭh" | "ṬH" | "ṭH" { return cursor, string(rune(P_th)), false }
	"ḍ" | "Ḍ" { return cursor, "ḍ", false }
	"ḍh" | "Ḍh" | "ḌH" | "ḍH" { return cursor, string(rune(P_dh)), false }
	"ṇ" | "Ṇ" { return cursor, "ṇ", false }
	"t" | "T" { return cursor, "t", false }
	"th" | "Th" | "TH" | "tH" { return cursor, string(rune(Pth)), false }
	"d" | "D" { return cursor, "d", false }
	"dh" | "Dh" | "DH" | "dH" { return cursor, string(rune(Pdh)), false }
	"n" | "N" { return cursor, "n", false }
	"p" | "P" { return cursor, "p", false }
	"ph" | "Ph" | "PH" | "pH" { return cursor, string(rune(Pph)), false }
	"b" | "B" { return cursor, "b", false }
	"bh" | "Bh" | "BH" | "bH" { return cursor, string(rune(Pbh)), false }
	"m" | "M" { return cursor, "m", false }
	"y" | "Y" { return cursor, "y", false }
	"r" | "R" { return cursor, "r", false }
	"l" | "L" { return cursor, "l", false }
	"v" | "V" { return cursor, "v", false }
	"ś" | "Ś" { return cursor, "ś", false }
	"ṣ" | "Ṣ" { return cursor, "ṣ", false }
	"s" | "S" { return cursor, "s", false }
	"h" | "H" { return cursor, "h", false }
	"ə" | "Ə" | "ә" | "Ә" { return cursor, "ə", false }
	"ə̄" | "Ə̄" | "ә̄" | "Ә̄" { return cursor, string(rune(Plongschwa)), false }
	[^] {
		r, _ := utf8.DecodeRuneInString(text[:cursor])
		if !unicode.IsLetter(r) && !unicode.IsDigit(r) {
			return cursor, "", true
		}
		return cursor, folder.String(string(r)), false
	}
	*/
	return 0, "", false
}

// consumeToken reads the token and converts the representation to a string to support multi-character graphemes.
// It continues to absorb combining characters sequentially until the matched length is reached.
func consumeToken(text string) (int, string, bool) {
	matchLen, rep, elide := lexPrefix(text)
	consumed := 0
	state := -1
	rest := text
	for consumed < matchLen {
		var cluster string
		cluster, rest, _, state = uniseg.StepString(rest, state)
		consumed += len(cluster)
	}
	return consumed, rep, elide
}

// lexReduced applies phonological transformations on the binary representation.
// It maps encoded sequences to a further reduced structural logic.
func lexReduced(encoded string) (int, rune) {
	cursor, marker := 0, 0
	_ = cursor
	_ = marker
	_ = encoded
	/*!re2c
	re2c:flags:8 = 1;
	re2c:yyfill:enable = 0;
	re2c:define:YYCTYPE = byte;
	re2c:define:YYPEEK = "peekByte(encoded, cursor)";
	re2c:define:YYSKIP = "cursor++";
	re2c:define:YYBACKUP = "marker = cursor";
	re2c:define:YYRESTORE = "cursor = marker";

	Pai = [\uE002];
	Pau = [\uE003];
	Pkh = [\uE004];
	Pgh = [\uE005];
	Pch = [\uE006];
	Pjh = [\uE007];
	P_th = [\uE008];
	P_dh = [\uE009];
	Pth = [\uE00A];
	Pdh = [\uE00B];
	Pph = [\uE00C];
	Pbh = [\uE00D];
	Plongschwa = [\uE00E];

	* { return 1, 0 }
	// Ignore all diacritics (except for the distinctions ṛ/r ḷ/l).
	// Treat aspirated and unaspirated as equivalent.
	// Treat nasals as equivalent (this isn't great though).
	"a" | "ā" { return cursor, 'a' }
	"i" | "ī" { return cursor, 'i' }
	"u" | "ū" { return cursor, 'u' }
	"ṛ" | "ṝ" { return cursor, 'ṛ' }
	"ḷ" | "ḹ" { return cursor, 'ḷ' }
	"e" { return cursor, 'e' }
	Pai { return cursor, Pai }
	"o" { return cursor, 'o' }
	Pau { return cursor, Pau }
	"ḥ" | "h" { return cursor, 'h' }
	"k" | Pkh | "g" | Pgh | "kk" | "k" Pkh | "gg" | "g" Pgh { return cursor, 'k' }
	"ṃ" | "ṅ" | "ñ" | "ṇ" | "n" | "m" | "ṅṅ" | "ññ" | "ṇṇ" | "nn" | "mm" { return cursor, 'n' }
	"c" | Pch | "j" | Pjh | "cc" | "c" Pch | "jj" | "j" Pjh { return cursor, 'c' }
	"ṭ" | P_th | "ḍ" | P_dh | "t" | Pth | "d" | Pdh | "ṭṭ" | "ṭ" P_th | "ḍḍ" | "ḍ" P_dh | "tt" | "t" Pth | "dd" | "d" Pdh { return cursor, 't' }
	"p" | Pph | "b" | Pbh | "pp" | "p" Pph | "bb" | "b" Pbh { return cursor, 'p' }
	"y" | "yy" { return cursor, 'y' }
	"r" | "rr" { return cursor, 'r' }
	"l" | "ll" { return cursor, 'l' }
	"v" | "vv" { return cursor, 'v' }
	"ś" | "ṣ" | "s" { return cursor, 's' }
	"ə" | Plongschwa { return cursor, 'ə' }
	// Fallback to exactly one byte to avoid fatal panics.
	[^] {
		r, size := utf8.DecodeRuneInString(encoded)
		return size, r
	}
	*/
	return 0, 0
}

// encodeSequence converts text into the binary sequence using string concatenation rather than rune writing.
// This accommodates the new multi-character mapping defined in the lexer block.
func encodeSequence(text string) string {
	var seq strings.Builder
	for len(text) > 0 {
		consumed, rep, elide := consumeToken(text)
		if elide {
			text = text[consumed:]
			continue
		}
		seq.WriteString(rep)
		text = text[consumed:]
	}
	return seq.String()
}

// encodeSequenceWithBounds maps the boundaries relative to the byte length of the string representations.
// It iterates over len(rep) which evaluates the number of bytes for proper structural offset mapping.
func encodeSequenceWithBounds(text string) (string, []int) {
	var seq strings.Builder
	var bounds []int
	cursor := 0
	for len(text) > 0 {
		consumed, rep, elide := consumeToken(text)
		if elide {
			cursor += consumed
			text = text[consumed:]
			continue
		}
		endCursor := cursor + consumed
		seq.WriteString(rep)
		n := len(rep)
		for j := 0; j < n; j++ {
			bounds = append(bounds, cursor, endCursor)
		}
		cursor = endCursor
		text = text[consumed:]
	}
	return seq.String(), bounds
}

// reduceSequence converts the encoded sequence to a reduced state without calculating positional bounds.
// It applies phonological neutralizations strictly for content matching.
func reduceSequence(encoded string) string {
	var reduced strings.Builder
	for len(encoded) > 0 {
		consumed, rep := lexReduced(encoded)
		if rep == 0 {
			break
		}
		reduced.WriteRune(rep)
		encoded = encoded[consumed:]
	}
	return reduced.String()
}

// reduceSequenceWithBounds converts the encoded sequence and maintains sequence bounds.
// It maps the reduced byte sequence back to its boundaries within the original encoded sequence.
func reduceSequenceWithBounds(encoded string) (string, []int) {
	var reduced strings.Builder
	var bounds []int
	cursor := 0
	for len(encoded) > 0 {
		consumed, rep := lexReduced(encoded)
		if rep == 0 {
			break
		}
		reduced.WriteRune(rep)
		n := utf8.RuneLen(rep)
		for j := 0; j < n; j++ {
			bounds = append(bounds, cursor, cursor+consumed)
		}
		cursor += consumed
		encoded = encoded[consumed:]
	}
	return reduced.String(), bounds
}

// lexNormalPrefix uses a finite state machine to identify the next sequence for normal mode.
// It returns the byte length of the matched sequence, its replacement string, and an elision flag.
func lexNormalPrefix(text string) (int, string, bool) {
	cursor, marker := 0, 0
	_ = cursor
	_ = marker
	_ = text
	/*!re2c
	re2c:flags:8 = 1;
	re2c:yyfill:enable = 0;
	re2c:define:YYCTYPE = byte;
	re2c:define:YYPEEK = "peekByte(text, cursor)";
	re2c:define:YYSKIP = "cursor++";
	re2c:define:YYBACKUP = "marker = cursor";
	re2c:define:YYRESTORE = "cursor = marker";
	* { return 1, "", true }
	"ă" | "Ă" { return cursor, "a", false }
	"ĕ" | "Ĕ" { return cursor, "e", false }
	"ĭ" | "Ĭ" { return cursor, "i", false }
	"ŏ" | "Ŏ" { return cursor, "o", false }
	"ŭ" | "Ŭ" { return cursor, "u", false }
	"æ" | "Æ" { return cursor, "ae", false }
	"œ" | "Œ" { return cursor, "oe", false }
	"đ" | "Đ" { return cursor, "d", false }
	"r̥" | "R̥" { return cursor, "ṛ", false }
	"r̥̄" | "R̥̄" { return cursor, "ṝ", false }
	"l̥" | "L̥"{ return cursor, "ḷ", false }
	"l̥̄" | "L̥̄" { return cursor, "ḹ", false }
	"ә" | "Ә" { return cursor, "ə", false }
	"ə̄" | "Ə̄" | "ә̄" | "Ә̄" { return cursor, string(Plongschwa), false }
	"ṁ" | "Ṁ" | "ṃ" | "Ṃ" | "m̐" | "M̐" | "m̃" | "M̃" { return cursor, "ṃ", false }
	"ḥ" | "Ḥ" | "ḫ" | "Ḫ" | "ẖ" | "H̱" { return cursor, "ḥ", false }
	// Fallback to Unicode case folding of the current full rune.
	[^] {
		r, size := utf8.DecodeRuneInString(text)
		return size, folder.String(string(r)), false
	}
	*/
	return 0, "", false
}

// consumeNormalToken reads the next token and aligns with grapheme boundaries.
// It discards trailing combining characters to keep only the base normalization.
// Note: this logic incorrectly handles Unicode Regional Indicator sequences.
// Because emoji flags are formed by pairs of Regional Indicators within a single
// grapheme cluster, the second indicator is deliberately but erroneously stripped.
func consumeNormalToken(text string) (int, string, bool) {
	matchLen, rep, elide := lexNormalPrefix(text)
	consumed := 0
	state := -1
	rest := text
	for consumed < matchLen {
		var cluster string
		cluster, rest, _, state = uniseg.StepString(rest, state)
		consumed += len(cluster)
	}
	return consumed, rep, elide
}

// transformNormal applies transformations for normal matching without allocating memory bounds.
// This fast path is crucial for eliminating garbage collection overhead during filtering.
func transformNormal(text string) string {
	var folded strings.Builder
	for len(text) > 0 {
		consumed, rep, elide := consumeNormalToken(text)
		if elide {
			text = text[consumed:]
			continue
		}
		folded.WriteString(rep)
		text = text[consumed:]
	}
	return folded.String()
}

// transformNormalWithBounds applies transformations and records interleaved index bounds.
// The returned array stores the exact original start and end byte offsets.
func transformNormalWithBounds(text string) (string, []int) {
	var folded strings.Builder
	var bounds []int
	cursor := 0
	for len(text) > 0 {
		consumed, rep, elide := consumeNormalToken(text)
		if elide {
			cursor += consumed
			text = text[consumed:]
			continue
		}
		endCursor := cursor + consumed
		n := len(rep)
		for j := 0; j < n; j++ {
			bounds = append(bounds, cursor, endCursor)
		}
		folded.WriteString(rep)
		cursor = endCursor
		text = text[consumed:]
	}
	return folded.String(), bounds
}

// transformNormalized executes the complete formb pipeline purely for content evaluation.
// It bypasses the generation of transitive index bounds to conserve memory.
func transformNormalized(text string) string {
	return reduceSequence(encodeSequence(text))
}

// transformNormalizedWithBounds tracks structural limits across the double normalization.
// It recursively retrieves the initial offsets using the boundaries of the reduced sequence.
func transformNormalizedWithBounds(text string) (string, []int) {
	seq, boundsA := encodeSequenceWithBounds(text)
	reduced, boundsB := reduceSequenceWithBounds(seq)
	var finalBounds []int
	for i := 0; i < len(reduced); i++ {
		startA := boundsB[2*i]
		endA := boundsB[2*i+1] - 1
		finalBounds = append(finalBounds, boundsA[2*startA], boundsA[2*endA+1])
	}
	return reduced, finalBounds
}

// transformPrefix executes the formc pipeline using only the prefix lexer.
// It maps text directly to the base semantic tokens without phonological reduction.
func transformPrefix(text string) string {
	return encodeSequence(text)
}

// transformPrefixWithBounds executes the formc pipeline and returns the original text bounds.
// It tracks positions through the single-layer prefix encoding sequence.
func transformPrefixWithBounds(text string) (string, []int) {
	return encodeSequenceWithBounds(text)
}

// transform acts as a fast text dispatcher ignoring positional metadata.
// It is intended for boolean evaluation matrices.
func transform(text string, mode string) string {
	if mode == "formb" {
		return transformNormalized(text)
	}
	if mode == "formc" {
		return transformPrefix(text)
	}
	return transformNormal(text)
}

// transformWithBounds computes structural offsets alongside textual mapping.
// It is strictly reserved for the final highlight processing layer.
func transformWithBounds(text string, mode string) (string, []int) {
	if mode == "formb" {
		return transformNormalizedWithBounds(text)
	}
	if mode == "formc" {
		return transformPrefixWithBounds(text)
	}
	return transformNormalWithBounds(text)
}
