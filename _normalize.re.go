//go:generate re2go -W -Werror -8 -o normalize.go _normalize.re.go

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
	"e" | "E" | "ĕ" | "Ĕ" { return cursor, Pe, false }
	"ai" | "Ai" | "AI" | "aI" { return cursor, Pai, false }
	"o" | "O" | "ŏ" | "Ŏ" { return cursor, Po, false }
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
	[^] {
		r, _ := utf8.DecodeRuneInString(text[:cursor])
		if !unicode.IsLetter(r) && !unicode.IsDigit(r) {
			return cursor, Pnul, true
		}
		return cursor, Pother, false
	}
	*/
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

// lexFormB applies second-order phonological transformations on the binary representation.
// It maps Form A sequences to a further reduced Form B logic.
func lexFormB(formA string) (int, int) {
	cursor, marker := 0, 0
	_ = marker
	/*!re2c
	re2c:flags:8 = 0;
	re2c:yyfill:enable = 0;
	re2c:define:YYCTYPE = byte;
	re2c:define:YYPEEK = "peekByte(formA, cursor)";
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
	Pother = "\x34";
	// Ignore all diacritics (except for the distinctions ṛ/r ḷ/l ḥ/h).
	// Treat aspirated and unaspirated as equivalent.
	// Treat nasals as equivalent.
	Pa | Paa { return cursor, Pa }
	Pi | Pii { return cursor, Pi }
	Pu | Puu { return cursor, Pu }
	P_r | P_rr { return cursor, Pṛ }
	P_l | P_ll { return cursor, Pḷ }
	Pe { return cursor, Pe }
	Pai { return cursor, Pai }
	Po { return cursor, Po }
	Pau { return cursor, Pau }
	P_h { return cursor, Pḥ }
	Pk | Pkh | Pg | Pgh { return cursor, Pk }
	P_m | Pf | Ppalataln | P_n | Pn | Pm { return cursor, Pn }
	Pc | Pch | Pj | Pjh { return cursor, Pc }
	P_t | P_th | P_d | P_dh | Pt | Pth | Pd | Pdh { return cursor, Pt }
	Pp | Pph | Pb | Pbh { return cursor, Pp }
	Py { return cursor, Py }
	Pr { return cursor, Pr }
	Pl { return cursor, Pl }
	Pv { return cursor, Pv }
	Ppalatals | P_s | Ps { return cursor, Ps }
	Ph { return cursor, Ph }
	Pschwa | Plongschwa { return cursor, Pschwa }
	Pother { return cursor, Pother }
	// Fallback to exactly one byte to avoid fatal panics.
	[^] { return 1, int(formA[0]) }
	*/
}

// toFormA converts UTF-8 text to the internal Form A (binary phonemic sequence).
// It maintains alignment arrays for original start and end byte positions.
func toFormA(text string) (string, []int, []int) {
	var formA strings.Builder
	var starts, ends []int
	cursor := 0
	for len(text) > 0 {
		consumed, rep, elide := consumeToken(text)
		if elide {
			cursor += consumed
			text = text[consumed:]
			continue
		}
		endCursor := cursor + consumed
		starts = append(starts, cursor)
		ends = append(ends, endCursor)
		formA.WriteByte(byte(rep))
		cursor = endCursor
		text = text[consumed:]
	}
	return formA.String(), starts, ends
}

// toFormB converts Form A to Form B, applying phonological neutralizations.
// It returns the mapped binary sequence and its index boundaries within Form A.
func toFormB(formA string) (string, []int, []int) {
	var formB strings.Builder
	var starts, ends []int
	cursor := 0
	for len(formA) > 0 {
		consumed, rep := lexFormB(formA)
		if rep == Pnul {
			break
		}
		starts = append(starts, cursor)
		ends = append(ends, cursor+consumed)
		formB.WriteByte(byte(rep))
		cursor += consumed
		formA = formA[consumed:]
	}
	return formB.String(), starts, ends
}

// transform acts as a dispatcher for text projection operations.
// It routes the input to the appropriate normalizer based on the requested mode.
func transform(text string, mode string) (string, []int, []int) {
	if mode == "normalized" {
		return transformNormalized(text)
	}
	return transformNormal(text)
}

// lexNormalPrefix uses a finite state machine to identify the next sequence for normal mode.
// It returns the byte length of the matched sequence, its replacement string, and an elision flag.
func lexNormalPrefix(text string) (int, string, bool) {
	cursor, marker := 0, 0
	/*!re2c
	re2c:flags:8 = 1;
	re2c:yyfill:enable = 0;
	re2c:define:YYCTYPE = byte;
	re2c:define:YYPEEK = "peekByte(text, cursor)";
	re2c:define:YYSKIP = "cursor++";
	re2c:define:YYBACKUP = "marker = cursor";
	re2c:define:YYRESTORE = "cursor = marker";
	* { return 1, "", true }
	// Add specific complex transformations for normal mode here.
	// For instance, explicitly mapping uppercase digraphs to lowercase:
	"KH" | "Kh" | "kH" { return cursor, "kh", false }
	"GH" | "Gh" | "gH" { return cursor, "gh", false }
	"CH" | "Ch" | "cH" { return cursor, "ch", false }
	"JH" | "Jh" | "jH" { return cursor, "jh", false }
	"ṬH" | "Ṭh" | "ṭH" { return cursor, "ṭh", false }
	"ḌH" | "Ḍh" | "ḍH" { return cursor, "ḍh", false }
	"TH" | "Th" | "tH" { return cursor, "th", false }
	"DH" | "Dh" | "dH" { return cursor, "dh", false }
	"PH" | "Ph" | "pH" { return cursor, "ph", false }
	"BH" | "Bh" | "bH" { return cursor, "bh", false }
	// Fallback to safe Unicode case folding of the current full rune.
	[^] {
		r, size := utf8.DecodeRuneInString(text)
		return size, cases.Fold().String(string(r)), false
	}
	*/
}

// consumeNormalToken reads the next token for normal mode and aligns with grapheme boundaries.
// It attaches any trailing combining characters to the replacement string.
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
	if consumed > matchLen && !elide {
		rep += text[matchLen:consumed]
	}
	return consumed, rep, elide
}

// transformNormal applies transformations for normal mode matching utilizing re2go.
// It preserves the original byte index boundaries for exact highlighting.
func transformNormal(text string) (string, []int, []int) {
	var folded strings.Builder
	var starts, ends []int
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
			starts = append(starts, cursor)
			ends = append(ends, endCursor)
		}
		folded.WriteString(rep)
		cursor = endCursor
		text = text[consumed:]
	}
	return folded.String(), starts, ends
}

// transformNormalized provides the complete normalization pipeline from UTF-8 to Form B.
// It maintains the strict index synchronization required by the search engine.
func transformNormalized(text string) (string, []int, []int) {
	formA, startsA, endsA := toFormA(text)
	formB, startsB, endsB := toFormB(formA)
	var finalStarts, finalEnds []int
	for i := 0; i < len(formB); i++ {
		finalStarts = append(finalStarts, startsA[startsB[i]])
		finalEnds = append(finalEnds, endsA[endsB[i]-1])
	}
	return formB, finalStarts, finalEnds
}
