// Memory-based search logic and AST evaluation.

package main

import (
	"bytes"
	"encoding/json"
	"sort"
	"strings"

	"golang.org/x/text/collate"
	"golang.org/x/text/language"
)

var titleCollator *collate.Collator

func init() {
	// Initialize collator with English configuration ignoring punctuation
	titleCollator = collate.New(language.Make("en-u-ka-shifted"))
}

func findDocument(ident string) *Document {
	// Search the in-memory corpus for a specific identifier
	mu.RLock()
	defer mu.RUnlock()
	for _, doc := range corpus {
		if doc.Ident == ident {
			return &doc
		}
	}
	return nil
}

func sortDocs(docs []Document, sortBy string) {
	// Apply the requested sorting algorithm to the document list
	if sortBy == "ident" {
		return
	}
	sort.Slice(docs, func(i, j int) bool {
		return compareDocs(docs[i], docs[j], sortBy)
	})
}

func myCompareString(c *collate.Collator, a, b string) int {
	// Compare two strings using the collator avoiding known bugs
	var buf collate.Buffer
	kA := c.KeyFromString(&buf, a)
	kB := c.KeyFromString(&buf, b)
	ret := bytes.Compare(kA, kB)
	buf.Reset()
	return ret
}

func compareDocs(d1, d2 Document, sortBy string) bool {
	// Compare two documents based on the specified sort criteria
	if sortBy == "title" {
		hasT1 := len(d1.Title) > 0
		hasT2 := len(d2.Title) > 0
		if hasT1 && hasT2 {
			return myCompareString(titleCollator, d1.Title[0], d2.Title[0]) < 0
		}
		if !hasT1 && !hasT2 {
			return d1.Ident < d2.Ident
		}
		return hasT1
	}
	return d1.Ident < d2.Ident
}

func paginateDocs(docs []Document, off, lim int) []Document {
	// Extract the requested page of results from the full list
	if off < 0 {
		off = 0
	}
	if off >= len(docs) {
		return []Document{}
	}
	end := len(docs)
	if lim > 0 {
		end = off + lim
		if end > len(docs) {
			end = len(docs)
		}
	}
	return docs[off:end]
}

func buildResults(docs []Document, q string) []SearchResult {
	// Generate search results with highlighted matches
	results := make([]SearchResult, 0, len(docs))
	for _, doc := range docs {
		results = append(results, matchDocument(doc, q))
	}
	return results
}

func parseQuery(qStr string) QueryNode {
	// Parse JSON query AST
	var q QueryNode
	json.Unmarshal([]byte(qStr), &q)
	return q
}

func filterDocs(qStr string) []Document {
	// Filter the corpus returning documents matching the query tree
	mu.RLock()
	snap := corpus
	mu.RUnlock()
	if qStr == "" {
		docs := make([]Document, len(snap))
		copy(docs, snap)
		return docs
	}
	q := parseQuery(qStr)
	var docs []Document
	for _, doc := range snap {
		if matchQuery(doc, q) {
			docs = append(docs, doc)
		}
	}
	return docs
}

func matchQuery(doc Document, q QueryNode) bool {
	// Evaluate the document against the query AST
	switch q.Op {
	case "and":
		return evalAnd(doc, q.Args)
	case "or":
		return evalOr(doc, q.Args)
	case "not":
		return !matchQuery(doc, *q.Arg)
	case "field":
		return matchField(doc, q.Field, q.Value, q.Mode)
	}
	return true
}

func evalAnd(d Document, args []QueryNode) bool {
	// Evaluate an AND node
	for _, arg := range args {
		if !matchQuery(d, arg) {
			return false
		}
	}
	return len(args) > 0
}

func evalOr(d Document, args []QueryNode) bool {
	// Evaluate an OR node
	for _, arg := range args {
		if matchQuery(d, arg) {
			return true
		}
	}
	return len(args) > 0
}

func containsMatcher(text, term, mode, field string) bool {
	// Resolve default mode based on the current field context
	if mode == "" {
		if field == "logical" {
			mode = "normalized"
		} else {
			mode = "normal"
		}
	}
	// Transform text and term according to the resolved mode
	transText, _, _ := transform(text, mode)
	transTerm, _, _ := transform(term, mode)
	return strings.Contains(transText, transTerm)
}

func matchField(d Document, field, val, mode string) bool {
	// Normalize field name to support dotted syntax natively
	field = strings.ReplaceAll(field, ".", "_")
	switch field {
	case "ident", "logical", "summary", "repo_id", "repo_name", "hand":
		return matchStringField(d, field, val, mode)
	case "title", "author", "author_ident", "author_name", "editor", "editor_ident", "editor_name", "lang", "lang_ident", "lang_name", "script", "script_ident", "script_name":
		return matchComplexField(d, field, val, mode)
	}
	return docMatchesAll(d, val, mode)
}

func matchStringField(d Document, field, val, mode string) bool {
	// Route simple string field evaluations to containsMatcher
	switch field {
	case "ident":
		return containsMatcher(d.Ident, val, mode, field)
	case "logical":
		return containsMatcher(d.Logical, val, mode, field)
	case "summary":
		return containsMatcher(d.Summary, val, mode, field)
	case "repo_id":
		return containsMatcher(d.RepoID, val, mode, field)
	case "repo_name":
		return containsMatcher(d.RepoName, val, mode, field)
	case "hand":
		return containsMatcher(d.Hand, val, mode, field)
	}
	return false
}

func matchComplexField(d Document, field, val, mode string) bool {
	// Route composite array properties to list matching helpers
	switch field {
	case "title":
		return listMatches(d.Title, val, mode, field)
	case "author":
		return listMatches(d.Author, val, mode, field)
	case "author_ident":
		return listMatchesParity(d.Author, val, mode, field, 0)
	case "author_name":
		return listMatchesParity(d.Author, val, mode, field, 1)
	case "editor":
		return listMatches(d.Editor, val, mode, field)
	case "editor_ident":
		return listMatchesParity(d.Editor, val, mode, field, 0)
	case "editor_name":
		return listMatchesParity(d.Editor, val, mode, field, 1)
	}
	return matchMatrixField(d, field, val, mode)
}

func matchMatrixField(d Document, field, val, mode string) bool {
	// Evaluate targeted matrix properties using selective column indices
	switch field {
	case "lang":
		return matrixMatchesCol(d.Lang, val, mode, field, -1)
	case "lang_ident":
		return matrixMatchesCol(d.Lang, val, mode, field, 0)
	case "lang_name":
		return matrixMatchesCol(d.Lang, val, mode, field, 1)
	case "script":
		return matrixMatchesCol(d.Script, val, mode, field, -1)
	case "script_ident":
		return matrixMatchesCol(d.Script, val, mode, field, 0)
	case "script_name":
		return matrixMatchesCol(d.Script, val, mode, field, 1)
	}
	return false
}

func docMatchesAll(d Document, val, mode string) bool {
	// Verify if any document field contains the value considering the mode
	if containsMatcher(d.Ident, val, mode, "ident") || containsMatcher(d.Logical, val, mode, "logical") {
		return true
	}
	if containsMatcher(d.Summary, val, mode, "summary") || containsMatcher(d.RepoID, val, mode, "repo_id") {
		return true
	}
	if containsMatcher(d.RepoName, val, mode, "repo_name") || containsMatcher(d.Hand, val, mode, "hand") {
		return true
	}
	if listMatches(d.Title, val, mode, "title") || listMatches(d.Author, val, mode, "author") {
		return true
	}
	if listMatches(d.Editor, val, mode, "editor") || matrixMatchesCol(d.Lang, val, mode, "lang", -1) {
		return true
	}
	return matrixMatchesCol(d.Script, val, mode, "script", -1)
}

func listMatches(list []string, q, mode, field string) bool {
	// Verify if any item in the list contains the query term considering the mode
	for _, item := range list {
		if containsMatcher(item, q, mode, field) {
			return true
		}
	}
	return false
}

func listMatchesParity(list []string, q, mode, field string, parity int) bool {
	// Verify if any item in the list matches considering parity and mode
	for i, item := range list {
		if parity != -1 && i%2 != parity {
			continue
		}
		if containsMatcher(item, q, mode, field) {
			return true
		}
	}
	return false
}

func matrixMatchesCol(mat [][]string, q, mode, field string, col int) bool {
	// Filter matrix evaluation according to a specified column index limitation
	for _, row := range mat {
		if col == -1 {
			limit := len(row)
			if limit > 2 {
				limit = 2
			}
			for j := 0; j < limit; j++ {
				if containsMatcher(row[j], q, mode, field) {
					return true
				}
			}
		} else if col < len(row) && containsMatcher(row[col], q, mode, field) {
			return true
		}
	}
	return false
}

func matchDocument(doc Document, qStr string) SearchResult {
	// Duplicate the document and apply highlights if necessary
	res := SearchResult{
		Ident: doc.Ident, Logical: doc.Logical,
		Title: cloneList(doc.Title), Summary: doc.Summary,
		RepoID: doc.RepoID, RepoName: doc.RepoName, Hand: doc.Hand,
		Author: cloneList(doc.Author), Editor: cloneList(doc.Editor),
		Lang: cloneMatrix(doc.Lang), Script: cloneMatrix(doc.Script),
	}
	if qStr == "" {
		return res
	}
	applyHighlights(&res, doc, qStr)
	return res
}

func extractTerms(q QueryNode) []QueryTerm {
	// Extract terms, their matching mode, and target field from the AST
	if q.Op == "field" {
		return []QueryTerm{{Field: q.Field, Value: q.Value, Mode: q.Mode}}
	}
	var terms []QueryTerm
	if q.Op == "and" || q.Op == "or" {
		for _, arg := range q.Args {
			terms = append(terms, extractTerms(arg)...)
		}
	}
	return terms
}

func termsForFields(terms []QueryTerm, fields ...string) []QueryTerm {
	// Filter a list of query terms retaining only those targeting specific fields
	var filtered []QueryTerm
	for _, t := range terms {
		if t.Field == "" {
			filtered = append(filtered, t)
			continue
		}
		normField := strings.ReplaceAll(t.Field, ".", "_")
		for _, f := range fields {
			if normField == f {
				filtered = append(filtered, t)
				break
			}
		}
	}
	return filtered
}

func applyHighlights(res *SearchResult, doc Document, qStr string) {
	// Inject highlight markers across all relevant fields
	q := parseQuery(qStr)
	terms := extractTerms(q)
	if len(terms) == 0 {
		return
	}
	highlightFields(res, doc, terms)
}

func highlightFields(res *SearchResult, doc Document, terms []QueryTerm) {
	// Apply highlights combining all query terms according to their target fields
	processFieldTerms(&res.Logical, doc.Logical, termsForFields(terms, "logical"), "logical")
	processFieldTerms(&res.Ident, doc.Ident, termsForFields(terms, "ident"), "ident")
	processFieldTerms(&res.Summary, doc.Summary, termsForFields(terms, "summary"), "summary")
	processFieldTerms(&res.RepoID, doc.RepoID, termsForFields(terms, "repo_id"), "repo_id")
	processFieldTerms(&res.RepoName, doc.RepoName, termsForFields(terms, "repo_name"), "repo_name")
	processFieldTerms(&res.Hand, doc.Hand, termsForFields(terms, "hand"), "hand")
	processListTerms(res.Title, doc.Title, termsForFields(terms, "title"), "title")
	processListTermsParity(res.Author, doc.Author, termsForFields(terms, "author", "author_ident"), "author_ident", 0)
	processListTermsParity(res.Author, doc.Author, termsForFields(terms, "author", "author_name"), "author_name", 1)
	processListTermsParity(res.Editor, doc.Editor, termsForFields(terms, "editor", "editor_ident"), "editor_ident", 0)
	processListTermsParity(res.Editor, doc.Editor, termsForFields(terms, "editor", "editor_name"), "editor_name", 1)
	highlightMatrixFields(res, terms)
}

func highlightMatrixFields(res *SearchResult, terms []QueryTerm) {
	// Direct specific matrix query terms to their dynamic row boundaries and fields
	highlightMatrixParity(res.Lang, terms, "lang", "script")
	highlightMatrixParity(res.Script, terms, "script", "lang")
}

func highlightMatrixParity(targets [][]string, terms []QueryTerm, primary, secondary string) {
	// Traverse matrices mapping alternating indices to primary and secondary semantic fields
	for i, row := range targets {
		for j, item := range row {
			base := secondary
			if j < 2 {
				base = primary
			}
			suffix := "_name"
			if j%2 == 0 {
				suffix = "_ident"
			}
			field := base + suffix
			processFieldTerms(&targets[i][j], item, termsForFields(terms, base, field), field)
		}
	}
}

func cloneList(src []string) []string {
	// Create a deep copy of a string slice
	dst := make([]string, len(src))
	copy(dst, src)
	return dst
}

func cloneMatrix(src [][]string) [][]string {
	// Create a deep copy of a string matrix
	dst := make([][]string, len(src))
	for i, row := range src {
		dst[i] = make([]string, len(row))
		copy(dst[i], row)
	}
	return dst
}

func processFieldTerms(target *string, source string, terms []QueryTerm, fieldName string) bool {
	// Detect occurrences and update the target string with markers
	var allIntervals [][2]int
	for _, term := range terms {
		allIntervals = append(allIntervals, findOccurrences(source, term.Value, term.Mode, fieldName)...)
	}
	if len(allIntervals) > 0 {
		*target = injectMarkers(source, allIntervals)
		return true
	}
	return false
}

func processListTerms(targets []string, sources []string, terms []QueryTerm, fieldName string) bool {
	// Apply highlight processing to a list of strings
	matched := false
	for i, item := range sources {
		if processFieldTerms(&targets[i], item, terms, fieldName) {
			matched = true
		}
	}
	return matched
}

func processListTermsParity(targets []string, sources []string, terms []QueryTerm, fieldName string, parity int) bool {
	// Apply highlight processing to a list of strings respecting parity
	matched := false
	for i, item := range sources {
		if parity != -1 && i%2 != parity {
			continue
		}
		if processFieldTerms(&targets[i], item, terms, fieldName) {
			matched = true
		}
	}
	return matched
}

type StringMapper func(string) (string, []int, []int)

func findOccurrences(text, term, mode, field string) [][2]int {
	// Resolve default mode based on the current field context
	if mode == "" {
		if field == "logical" {
			mode = "normalized"
		} else {
			mode = "normal"
		}
	}
	// Delegate the search to the universal mapping function
	mapper := func(s string) (string, []int, []int) {
		return transform(s, mode)
	}
	return findOccurrencesWithMapping(text, term, mapper)
}

func findOccurrencesWithMapping(text, term string, mapper StringMapper) [][2]int {
	// Identify start and end indices using a text mapping function
	transText, starts, ends := mapper(text)
	transTerm, _, _ := mapper(term)
	var matches [][2]int
	termLen := len(transTerm)
	if termLen == 0 {
		return matches
	}
	start := 0
	for {
		idx := strings.Index(transText[start:], transTerm)
		if idx == -1 {
			break
		}
		absStart := start + idx
		origStart := starts[absStart]
		origEnd := ends[absStart+termLen-1]
		matches = append(matches, [2]int{origStart, origEnd})
		start = absStart + 1
	}
	return matches
}

type Point struct {
	idx  int
	kind int
}

func injectMarkers(text string, intervals [][2]int) string {
	// Insert boundary markers around all identified occurrences
	if len(intervals) == 0 {
		return text
	}
	points := buildPoints(intervals)
	var sb strings.Builder
	cursor, depth := 0, 0
	for _, p := range points {
		if p.idx > cursor {
			sb.WriteString(text[cursor:p.idx])
			cursor = p.idx
		}
		depth = processPoint(p, depth, &sb)
	}
	if cursor < len(text) {
		sb.WriteString(text[cursor:])
	}
	return sb.String()
}

func buildPoints(intervals [][2]int) []Point {
	// Transform intervals into a sorted list of boundary points
	var points []Point
	for _, interval := range intervals {
		points = append(points, Point{interval[0], 1})
		points = append(points, Point{interval[1], -1})
	}
	sortPoints(points)
	return points
}

func sortPoints(points []Point) {
	// Sort boundary points sequentially ensuring logical nesting
	sort.Slice(points, func(i, j int) bool {
		if points[i].idx != points[j].idx {
			return points[i].idx < points[j].idx
		}
		return points[i].kind < points[j].kind
	})
}

func processPoint(p Point, depth int, sb *strings.Builder) int {
	// Compute nesting depth and emit structural markers
	if p.kind == 1 {
		if depth == 0 {
			sb.WriteString(MarkerStart)
		}
		return depth + 1
	}
	newDepth := depth - 1
	if newDepth == 0 {
		sb.WriteString(MarkerEnd)
	}
	return newDepth
}
