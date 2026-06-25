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

const (
	Pnul = iota
	Pa
	Pā
	Pi
	Pī
	Pu
	Pū
	Pṛ
	Pṝ
	Pḷ
	Pḹ
	Pe
	Pai
	Po
	Pau
	Pṃ
	Pḥ
	Pk
	Pkh
	Pg
	Pgh
	Pṅ
	Pc
	Pch
	Pj
	Pjh
	Pñ
	Pṭ
	Pṭh
	Pḍ
	Pḍh
	Pṇ
	Pt
	Pth
	Pd
	Pdh
	Pn
	Pp
	Pph
	Pb
	Pbh
	Pm
	Py
	Pr
	Pl
	Pv
	Pś
	Pṣ
	Ps
	Ph
	Pschwa
	Plongschwa
	P0
	P1
	P2
	P3
	P4
	P5
	P6
	P7
	P8
	P9
	Pother
)

var phonemeLookup = []string{
	"!",
	"a", "ā", "i", "ī", "u", "ū",
	"ṛ", "ṝ", "ḷ", "ḹ",
	"e", "ai", "o", "au",
	"ṃ", "ḥ",
	"k", "kh", "g", "gh", "ṅ",
	"c", "ch", "j", "jh", "ñ",
	"ṭ", "ṭh", "ḍ", "ḍh", "ṇ",
	"t", "th", "d", "dh", "n",
	"p", "ph", "b", "bh", "m",
	"y", "r", "l", "v",
	"ś", "ṣ", "s", "h",
	"ə", "ə̄",
	"0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
	"?",
}

// peekByte safely reads a byte from a string to prevent out-of-bounds panics in re2c.
// It returns 0 when the cursor reaches or exceeds the string length.
func peekByte(s string, i int) byte {
	if i < len(s) {
		return s[i]
	}
	return 0
}

// makePrintable converts the internal binary representation back to readable characters.
// It maps sequence codes to their IAST equivalents for debugging purposes.
func makePrintable(s string) string {
	var buf strings.Builder
	for i := 0; i < len(s); i++ {
		c := int(s[i])
		buf.WriteString(phonemeLookup[c])
	}
	return buf.String()
}

// lexPrefix uses a finite state machine to identify the next semantic sequence.
// It returns the byte length of the matched sequence, its replacement, and an elision flag.
func lexPrefix(text string) (int, int, bool) {
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
	* { return 1, Pnul, true }
	// In Tamil, the character "'" represents an elided "u" when it appears
	// at the end of a word (viz. before a non-alphanumeric char or the
	// empty string), as in:
	//     kaṇṇāṟṟ’ iraṇṭāñ
	//     uttirōttar’-abhivriddhi
	// But when "'" appears at the beginning of a word (viz. immediately
	// before an alphabetic char), it represents the avagraha, even in
	// Tamil, as in:
	//     durvvāso-’nukāribhyaḥ
	//     bar ’nukāribhyaḥ
	//     sthirayogo’pi # not supposed to happen, but does happen.
	// Ideally, we should resolve the ambiguity, and transform the "'" into
	// an "a" or an "u". But for now, for simplicity, we just turn this
	// character into an "a".
	// The sequences "'!" and "’!" always represent the avagraha, e.g.
	// ’!pi = 'pi = api
	"a" | "A" | "ă" | "Ă" | "'" | "’" | "'!" | "’!" { return cursor, Pa, false }
	"ā" | "Ā" { return cursor, Pā, false }
	"i" | "I" | "ĭ" | "Ĭ" { return cursor, Pi, false }
	"ī" | "Ī" { return cursor, Pī, false }
	"u" | "U" | "ŭ" | "Ŭ" { return cursor, Pu, false }
	"ū" | "Ū" { return cursor, Pū, false }
	"ṛ" | "Ṛ" | "r̥" | "R̥" { return cursor, Pṛ, false }
	"ṝ" | "Ṝ" | "r̥̄" | "R̥̄" { return cursor, Pṝ, false }
	"ḷ" | "Ḷ" | "l̥" | "L̥"{ return cursor, Pḷ, false }
	"ḹ" | "Ḹ" | "l̥̄" | "L̥̄" { return cursor, Pḹ, false }
	"e" | "E" | "ĕ" | "Ĕ" | "ē" | "Ē" { return cursor, Pe, false }
	"ai" | "Ai" | "AI" | "aI" { return cursor, Pai, false }
	"o" | "O" | "ŏ" | "Ŏ" | "ō" | "Ō" { return cursor, Po, false }
	"au" | "Au" | "AU" | "aU" { return cursor, Pau, false }
	// Anusvara and anunāsika, Cam anusvāra-candra, all treated as the anusvara.
	"ṁ" | "Ṁ" | "ṃ" | "Ṃ" | "m̐" | "M̐" | "m̃" | "M̃" { return cursor, Pṃ, false }
	// Upadhmānīya and jihvāmūlīya. Just fold them to a visarga.
	"ḥ" | "Ḥ" | "ḫ" | "Ḫ" | "ẖ" | "H̱" { return cursor, Pḥ, false }
	"k" | "K" { return cursor, Pk, false }
	"kh" | "Kh" | "KH" | "kH" { return cursor, Pkh, false }
	"g" | "G" { return cursor, Pg, false }
	"gh" | "Gh" | "GH" | "gH" { return cursor, Pgh, false }
	"ṅ" | "Ṅ" { return cursor, Pṅ, false }
	"c" | "C" { return cursor, Pc, false }
	"ch" | "Ch" | "CH" | "cH" { return cursor, Pch, false }
	"j" | "J" { return cursor, Pj, false }
	"jh" | "Jh" | "JH" | "jH" { return cursor, Pjh, false }
	"ñ" | "Ñ" { return cursor, Pñ, false }
	"ṭ" | "Ṭ" { return cursor, Pṭ, false }
	"ṭh" | "Ṭh" | "ṬH" | "ṭH" { return cursor, Pṭh, false }
	"ḍ" | "Ḍ" { return cursor, Pḍ, false }
	"ḍh" | "Ḍh" | "ḌH" | "ḍH" { return cursor, Pḍh, false }
	"ṇ" | "Ṇ" { return cursor, Pṇ, false }
	"t" | "T" { return cursor, Pt, false }
	"th" | "Th" | "TH" | "tH" { return cursor, Pth, false }
	"d" | "D" { return cursor, Pd, false }
	"dh" | "Dh" | "DH" | "dH" { return cursor, Pdh, false }
	"n" | "N" { return cursor, Pn, false }
	"p" | "P" { return cursor, Pp, false }
	"ph" | "Ph" | "PH" | "pH" { return cursor, Pph, false }
	"b" | "B" { return cursor, Pb, false }
	"bh" | "Bh" | "BH" | "bH" { return cursor, Pbh, false }
	"m" | "M" { return cursor, Pm, false }
	"y" | "Y" { return cursor, Py, false }
	"r" | "R" { return cursor, Pr, false }
	"l" | "L" { return cursor, Pl, false }
	"v" | "V" { return cursor, Pv, false }
	"ś" | "Ś" { return cursor, Pś, false }
	"ṣ" | "Ṣ" { return cursor, Pṣ, false }
	"s" | "S" { return cursor, Ps, false }
	"h" | "H" { return cursor, Ph, false }
	// Javanese/Balinese pepet. For the following, we both map
	// LATIN SMALL LETTER SCHWA (the correct character) and CYRILLIC
	// SMALL LETTER SCHWA (incorrect one), in both the upper- and lowercase versions.
	"ə" | "Ə" | "ә" | "Ә" { return cursor, Pschwa, false }
	"ə̄" | "Ə̄" | "ә̄" | "Ә̄" { return cursor, Plongschwa, false }
	"0" { return cursor, P0, false }
	"1" { return cursor, P1, false }
	"2" { return cursor, P2, false }
	"3" { return cursor, P3, false }
	"4" { return cursor, P4, false }
	"5" { return cursor, P5, false }
	"6" { return cursor, P6, false }
	"7" { return cursor, P7, false }
	"8" { return cursor, P8, false }
	"9" { return cursor, P9, false }
	[^] {
		r, _ := utf8.DecodeRuneInString(text[:cursor])
		if !unicode.IsLetter(r) && !unicode.IsDigit(r) {
			return cursor, Pnul, true
		}
		return cursor, Pother, false
	}
	*/
	return 0, 0, false
}

// consumeToken reads the next token and aligns the cursor with grapheme boundaries.
// It absorbs any trailing combining characters attached to the recognized sequence.
func consumeToken(text string) (int, int, bool) {
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
func lexReduced(encoded string) (int, int) {
	cursor, marker := 0, 0
	_ = cursor
	_ = marker
	_ = encoded
	/*!re2c
	re2c:flags:8 = 0;
	re2c:yyfill:enable = 0;
	re2c:define:YYCTYPE = byte;
	re2c:define:YYPEEK = "peekByte(encoded, cursor)";
	re2c:define:YYSKIP = "cursor++";
	re2c:define:YYBACKUP = "marker = cursor";
	re2c:define:YYRESTORE = "cursor = marker";
	* { return 1, Pnul }
	"\x00" { return 1, Pnul }
	Pa = "\x01";
	Paa = "\x02";
	Pi = "\x03";
	Pii = "\x04";
	Pu = "\x05";
	Puu = "\x06";
	P_r = "\x07";
	P_rr = "\x08";
	P_l = "\x09";
	P_ll = "\x0A";
	Pe = "\x0B";
	Pai = "\x0C";
	Po = "\x0D";
	Pau = "\x0E";
	P_m = "\x0F";
	P_h = "\x10";
	Pk = "\x11";
	Pkh = "\x12";
	Pg = "\x13";
	Pgh = "\x14";
	Pf = "\x15";
	Pc = "\x16";
	Pch = "\x17";
	Pj = "\x18";
	Pjh = "\x19";
	Ppalataln = "\x1A";
	P_t = "\x1B";
	P_th = "\x1C";
	P_d = "\x1D";
	P_dh = "\x1E";
	P_n = "\x1F";
	Pt = "\x20";
	Pth = "\x21";
	Pd = "\x22";
	Pdh = "\x23";
	Pn = "\x24";
	Pp = "\x25";
	Pph = "\x26";
	Pb = "\x27";
	Pbh = "\x28";
	Pm = "\x29";
	Py = "\x2A";
	Pr = "\x2B";
	Pl = "\x2C";
	Pv = "\x2D";
	Ppalatals = "\x2E";
	P_s = "\x2F";
	Ps = "\x30";
	Ph = "\x31";
	Pschwa = "\x32";
	Plongschwa = "\x33";
	P0 = "\x34";
	P1 = "\x35";
	P2 = "\x36";
	P3 = "\x37";
	P4 = "\x38";
	P5 = "\x39";
	P6 = "\x3A";
	P7 = "\x3B";
	P8 = "\x3C";
	P9 = "\x3D";
	Pother = "\x3E";
	// Ignore all diacritics (except for the distinctions ṛ/r ḷ/l).
	// Treat aspirated and unaspirated as equivalent.
	// Treat nasals as equivalent (this isn't great though).
	Pa | Paa { return cursor, Pa }
	Pi | Pii { return cursor, Pi }
	Pu | Puu { return cursor, Pu }
	P_r | P_rr { return cursor, Pṛ }
	P_l | P_ll { return cursor, Pḷ }
	Pe { return cursor, Pe }
	Pai { return cursor, Pai }
	Po { return cursor, Po }
	Pau { return cursor, Pau }
	P_h | Ph { return cursor, Ph }
	Pk | Pkh | Pg | Pgh | Pk Pk | Pk Pkh | Pg Pg | Pg Pgh { return cursor, Pk }
	P_m | Pf | Ppalataln | P_n | Pn | Pm | Pf Pf | Ppalataln Ppalataln | P_n P_n | Pn Pn | Pm Pm { return cursor, Pn }
	Pc | Pch | Pj | Pjh | Pc Pc | Pc Pch | Pj Pj | Pj Pjh { return cursor, Pc }
	P_t | P_th | P_d | P_dh | Pt | Pth | Pd | Pdh | P_t P_t | P_t P_th | P_d P_d | P_d P_dh | Pt Pt | Pt Pth | Pd Pd | Pd Pdh { return cursor, Pt }
	Pp | Pph | Pb | Pbh | Pp Pp | Pp Pph | Pb Pb | Pb Pbh { return cursor, Pp }
	Py | Py Py { return cursor, Py }
	Pr | Pr Pr { return cursor, Pr }
	Pl | Pl Pl { return cursor, Pl }
	Pv | Pv Pv { return cursor, Pv }
	Ppalatals | P_s | Ps { return cursor, Ps }
	Pschwa | Plongschwa { return cursor, Pschwa }
	Pother { return cursor, Pother }
	// Fallback to exactly one byte to avoid fatal panics.
	[^] { return 1, int(encoded[0]) }
	*/
	return 0, 0
}

// encodeSequence converts UTF-8 text to the internal binary sequence without allocating bounds.
// It is optimized for high-speed evaluation during the filtering phase.
func encodeSequence(text string) string {
	var seq strings.Builder
	for len(text) > 0 {
		consumed, rep, elide := consumeToken(text)
		if elide {
			text = text[consumed:]
			continue
		}
		seq.WriteByte(byte(rep))
		text = text[consumed:]
	}
	return seq.String()
}

// encodeSequenceWithBounds converts text to the internal sequence and returns an interleaved bounds array.
// The array alternates original start and original end indices for each byte.
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
		seq.WriteByte(byte(rep))
		bounds = append(bounds, cursor, endCursor)
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
		if rep == Pnul {
			break
		}
		reduced.WriteByte(byte(rep))
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
		if rep == Pnul {
			break
		}
		reduced.WriteByte(byte(rep))
		bounds = append(bounds, cursor, cursor+consumed)
		cursor += consumed
		encoded = encoded[consumed:]
	}
	return reduced.String(), bounds
}

const normalFirst = 0xE002
const Slongschwa = string(rune(normalFirst + Plongschwa))

var folder = cases.Fold()

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
	"r̥̄" | "R̥̄" { return cursor, "ṹ", false }
	"l̥" | "L̥"{ return cursor, "ḷ", false }
	"l̥̄" | "L̥̄" { return cursor, "ḹ", false }
	"ә" | "Ә" { return cursor, "ə", false }
	"ə̄" | "Ə̄" | "ә̄" | "Ә̄" { return cursor, Slongschwa, false }
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

// transform acts as a fast text dispatcher ignoring positional metadata.
// It is intended for boolean evaluation matrices.
func transform(text string, mode string) string {
	if mode == "formb" {
		return transformNormalized(text)
	}
	return transformNormal(text)
}

// transformWithBounds computes structural offsets alongside textual mapping.
// It is strictly reserved for the final highlight processing layer.
func transformWithBounds(text string, mode string) (string, []int) {
	if mode == "formb" {
		return transformNormalizedWithBounds(text)
	}
	return transformNormalWithBounds(text)
}
