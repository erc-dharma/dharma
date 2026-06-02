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

func (c *TransformCache) get(text, mode string) string {
	// Execute lazy transformation falling back to immediate evaluation if nil
	if c == nil {
		return transform(text, mode)
	}
	if mode == "normalized" {
		c.onceNorm.Do(func() {
			c.normalized = transform(text, "normalized")
		})
		return c.normalized
	}
	c.onceNormal.Do(func() {
		c.normal = transform(text, "normal")
	})
	return c.normal
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
	if sortBy == "ident" {
		return d1.Ident < d2.Ident
	}
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
	case "seq", "near":
		return matchSeqField(doc, q)
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

func containsMatcher(cache *TransformCache, text, term, mode, field string) bool {
	// Verify text inclusion utilizing the configured transformation cache
	if mode == "" {
		if field == "logical" {
			mode = "normalized"
		} else {
			mode = "normal"
		}
	}
	transText := cache.get(text, mode)
	transTerm := transform(term, mode)
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
		return containsMatcher(d.Cache.Ident, d.Ident, val, mode, field)
	case "logical":
		return containsMatcher(d.Cache.Logical, d.Logical, val, mode, field)
	case "summary":
		return containsMatcher(d.Cache.Summary, d.Summary, val, mode, field)
	case "repo_id":
		return containsMatcher(d.Cache.RepoID, d.RepoID, val, mode, field)
	case "repo_name":
		return containsMatcher(d.Cache.RepoName, d.RepoName, val, mode, field)
	case "hand":
		return containsMatcher(d.Cache.Hand, d.Hand, val, mode, field)
	}
	return false
}

func matchComplexField(d Document, field, val, mode string) bool {
	// Route composite array properties to list matching helpers
	switch field {
	case "title":
		return listMatches(d.Title, d.Cache.Title, val, mode, field)
	case "author":
		return listMatches(d.Author, d.Cache.Author, val, mode, field)
	case "author_ident":
		return listMatchesParity(d.Author, d.Cache.Author, val, mode, field, 0)
	case "author_name":
		return listMatchesParity(d.Author, d.Cache.Author, val, mode, field, 1)
	case "editor":
		return listMatches(d.Editor, d.Cache.Editor, val, mode, field)
	case "editor_ident":
		return listMatchesParity(d.Editor, d.Cache.Editor, val, mode, field, 0)
	case "editor_name":
		return listMatchesParity(d.Editor, d.Cache.Editor, val, mode, field, 1)
	}
	return matchMatrixField(d, field, val, mode)
}

func matchMatrixField(d Document, field, val, mode string) bool {
	// Evaluate targeted matrix properties using selective column indices
	switch field {
	case "lang":
		return matrixMatchesCol(d.Lang, d.Cache.Lang, val, mode, field, -1)
	case "lang_ident":
		return matrixMatchesCol(d.Lang, d.Cache.Lang, val, mode, field, 0)
	case "lang_name":
		return matrixMatchesCol(d.Lang, d.Cache.Lang, val, mode, field, 1)
	case "script":
		return matrixMatchesCol(d.Script, d.Cache.Script, val, mode, field, -1)
	case "script_ident":
		return matrixMatchesCol(d.Script, d.Cache.Script, val, mode, field, 0)
	case "script_name":
		return matrixMatchesCol(d.Script, d.Cache.Script, val, mode, field, 1)
	}
	return false
}

func docMatchesAll(d Document, val, mode string) bool {
	// Verify if any document field contains the value considering the mode
	if containsMatcher(d.Cache.Logical, d.Logical, val, mode, "logical") || containsMatcher(d.Cache.Ident, d.Ident, val, mode, "ident") {
		return true
	}
	if containsMatcher(d.Cache.Summary, d.Summary, val, mode, "summary") || containsMatcher(d.Cache.RepoID, d.RepoID, val, mode, "repo_id") {
		return true
	}
	if containsMatcher(d.Cache.RepoName, d.RepoName, val, mode, "repo_name") || containsMatcher(d.Cache.Hand, d.Hand, val, mode, "hand") {
		return true
	}
	if listMatches(d.Title, d.Cache.Title, val, mode, "title") || listMatches(d.Author, d.Cache.Author, val, mode, "author") {
		return true
	}
	if listMatches(d.Editor, d.Cache.Editor, val, mode, "editor") || matrixMatchesCol(d.Lang, d.Cache.Lang, val, mode, "lang", -1) {
		return true
	}
	return matrixMatchesCol(d.Script, d.Cache.Script, val, mode, "script", -1)
}

func listMatches(list []string, caches []*TransformCache, q, mode, field string) bool {
	// Verify if any item in the list contains the query term
	for i, item := range list {
		var c *TransformCache
		if caches != nil && i < len(caches) {
			c = caches[i]
		}
		if containsMatcher(c, item, q, mode, field) {
			return true
		}
	}
	return false
}

func listMatchesParity(list []string, caches []*TransformCache, q, mode, field string, parity int) bool {
	// Verify if any item in the list matches considering parity and mode
	for i, item := range list {
		if parity != -1 && i%2 != parity {
			continue
		}
		var c *TransformCache
		if caches != nil && i < len(caches) {
			c = caches[i]
		}
		if containsMatcher(c, item, q, mode, field) {
			return true
		}
	}
	return false
}

func matrixMatchesCol(mat [][]string, caches [][]*TransformCache, q, mode, field string, col int) bool {
	// Filter matrix evaluation according to a specified column index limitation
	for i, row := range mat {
		var rowCaches []*TransformCache
		if caches != nil && i < len(caches) {
			rowCaches = caches[i]
		}
		if col == -1 {
			if scanRowLimit(row, rowCaches, q, mode, field) {
				return true
			}
		} else if col < len(row) && scanRowCol(row, rowCaches, q, mode, field, col) {
			return true
		}
	}
	return false
}

func scanRowLimit(row []string, rowCaches []*TransformCache, q, mode, field string) bool {
	// Scan exclusively the first two elements of a matrix row
	limit := len(row)
	if limit > 2 {
		limit = 2
	}
	for j := 0; j < limit; j++ {
		var c *TransformCache
		if rowCaches != nil && j < len(rowCaches) {
			c = rowCaches[j]
		}
		if containsMatcher(c, row[j], q, mode, field) {
			return true
		}
	}
	return false
}

func scanRowCol(row []string, rowCaches []*TransformCache, q, mode, field string, col int) bool {
	// Evaluate a specific column index within a matrix row
	var c *TransformCache
	if rowCaches != nil && col < len(rowCaches) {
		c = rowCaches[col]
	}
	return containsMatcher(c, row[col], q, mode, field)
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
	if q.Op == "and" || q.Op == "or" || q.Op == "seq" || q.Op == "near" {
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
	highlightMatrixFields(res, doc, terms)
}

func highlightMatrixFields(res *SearchResult, doc Document, terms []QueryTerm) {
	// Direct specific matrix query terms to their respective row boundaries and columns
	processMatrixTermsCol(res.Lang, doc.Lang, termsForFields(terms, "lang", "lang_ident"), "lang_ident", 0)
	processMatrixTermsCol(res.Lang, doc.Lang, termsForFields(terms, "lang", "lang_name"), "lang_name", 1)
	processMatrixTermsCol(res.Script, doc.Script, termsForFields(terms, "script", "script_ident"), "script_ident", 0)
	processMatrixTermsCol(res.Script, doc.Script, termsForFields(terms, "script", "script_name"), "script_name", 1)
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

func processMatrixTermsCol(targets [][]string, sources [][]string, terms []QueryTerm, fieldName string, col int) bool {
	// Apply highlight processing to targeted matrix components utilizing specific column rules
	matched := false
	for i, row := range sources {
		if col == -1 {
			limit := len(row)
			if limit > 2 {
				limit = 2
			}
			for j := 0; j < limit; j++ {
				if processFieldTerms(&targets[i][j], row[j], terms, fieldName) {
					matched = true
				}
			}
		} else if col < len(row) && processFieldTerms(&targets[i][col], row[col], terms, fieldName) {
			matched = true
		}
	}
	return matched
}

// StringMapper defines the signature for transformation functions computing text boundaries
type StringMapper func(string) (string, []int)

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
	mapper := func(s string) (string, []int) {
		return transformWithBounds(s, mode)
	}
	return findOccurrencesWithMapping(text, term, mapper)
}

func findOccurrencesWithMapping(text, term string, mapper StringMapper) [][2]int {
	// Identify start and end indices using a text mapping function
	transText, bounds := mapper(text)
	transTerm, _ := mapper(term)
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
		origStart := bounds[2*absStart]
		origEnd := bounds[2*(absStart+termLen-1)+1]
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

func getFieldName(q QueryNode) string {
	// Retrieve the nominal field attribute traversing the syntax tree
	if q.Op == "field" {
		return q.Field
	}
	if len(q.Args) > 0 {
		return getFieldName(q.Args[0])
	}
	return ""
}

func findSeqOccurrences(text string, q QueryNode) [][2]int {
	// Calculate boundaries of sequence intersections respecting positional distances
	if q.Op == "field" {
		return findOccurrences(text, q.Value, q.Mode, q.Field)
	}
	var matches [][2]int
	if q.Op == "near" && len(q.Args) >= 2 {
		matches = append(matches, evalSeqPair(text, q.Args[0], q.Args[1], q.X, q.Y)...)
		matches = append(matches, evalSeqPair(text, q.Args[1], q.Args[0], q.X, q.Y)...)
		return matches
	}
	if q.Op != "seq" || len(q.Args) < 2 {
		return matches
	}
	return evalSeqPair(text, q.Args[0], q.Args[1], q.X, q.Y)
}

func evalSeqPair(text string, left, right QueryNode, x, y int) [][2]int {
	// Helper function to evaluate ordered adjacency ensuring metric limits
	var matches [][2]int
	leftOpt := findSeqOccurrences(text, left)
	rightOpt := findSeqOccurrences(text, right)
	for _, l := range leftOpt {
		for _, r := range rightOpt {
			dist := r[0] - l[1]
			if dist >= x && (y == -1 || dist < y) {
				matches = append(matches, [2]int{l[0], r[1]})
			}
		}
	}
	return matches
}

func matchSeqField(d Document, q QueryNode) bool {
	// Route sequential evaluations utilizing dynamic positional constraints
	field := getFieldName(q)
	field = strings.ReplaceAll(field, ".", "_")
	switch field {
	case "ident":
		return len(findSeqOccurrences(d.Ident, q)) > 0
	case "logical":
		return len(findSeqOccurrences(d.Logical, q)) > 0
	case "summary":
		return len(findSeqOccurrences(d.Summary, q)) > 0
	case "repo_id":
		return len(findSeqOccurrences(d.RepoID, q)) > 0
	case "repo_name":
		return len(findSeqOccurrences(d.RepoName, q)) > 0
	case "hand":
		return len(findSeqOccurrences(d.Hand, q)) > 0
	}
	return matchComplexSeqField(d, field, q)
}

func matchComplexSeqField(d Document, field string, q QueryNode) bool {
	// Delegate array properties ensuring constraints across multiple nodes
	switch field {
	case "title":
		return listSeqMatches(d.Title, q)
	case "author":
		return listSeqMatches(d.Author, q)
	case "author_ident":
		return listSeqMatchesParity(d.Author, q, 0)
	case "author_name":
		return listSeqMatchesParity(d.Author, q, 1)
	case "editor":
		return listSeqMatches(d.Editor, q)
	case "editor_ident":
		return listSeqMatchesParity(d.Editor, q, 0)
	case "editor_name":
		return listSeqMatchesParity(d.Editor, q, 1)
	}
	return matchMatrixSeqField(d, field, q)
}

func matchMatrixSeqField(d Document, field string, q QueryNode) bool {
	// Distribute matrix validations bounding specific column parameters
	switch field {
	case "lang":
		return matrixSeqMatchesCol(d.Lang, q, -1)
	case "lang_ident":
		return matrixSeqMatchesCol(d.Lang, q, 0)
	case "lang_name":
		return matrixSeqMatchesCol(d.Lang, q, 1)
	case "script":
		return matrixSeqMatchesCol(d.Script, q, -1)
	case "script_ident":
		return matrixSeqMatchesCol(d.Script, q, 0)
	case "script_name":
		return matrixSeqMatchesCol(d.Script, q, 1)
	}
	return docSeqMatchesAll(d, q)
}

func listSeqMatches(list []string, q QueryNode) bool {
	// Evaluate if any string element successfully integrates the sequence conditions
	for _, item := range list {
		if len(findSeqOccurrences(item, q)) > 0 {
			return true
		}
	}
	return false
}

func listSeqMatchesParity(list []string, q QueryNode, parity int) bool {
	// Check matrix nodes preserving boundaries under positional restrictions
	for i, item := range list {
		if i%2 == parity && len(findSeqOccurrences(item, q)) > 0 {
			return true
		}
	}
	return false
}

func matrixSeqMatchesCol(mat [][]string, q QueryNode, col int) bool {
	// Process matrix vectors to assess if elements sustain sequence validity
	for _, row := range mat {
		if col == -1 {
			limit := len(row)
			if limit > 2 {
				limit = 2
			}
			for j := 0; j < limit; j++ {
				if len(findSeqOccurrences(row[j], q)) > 0 {
					return true
				}
			}
		} else if col < len(row) && len(findSeqOccurrences(row[col], q)) > 0 {
			return true
		}
	}
	return false
}

func docSeqMatchesAll(d Document, q QueryNode) bool {
	// Determine validation status across the entirety of text fields
	if len(findSeqOccurrences(d.Logical, q)) > 0 || len(findSeqOccurrences(d.Ident, q)) > 0 {
		return true
	}
	if len(findSeqOccurrences(d.Summary, q)) > 0 || len(findSeqOccurrences(d.RepoID, q)) > 0 {
		return true
	}
	if len(findSeqOccurrences(d.RepoName, q)) > 0 || len(findSeqOccurrences(d.Hand, q)) > 0 {
		return true
	}
	if listSeqMatches(d.Title, q) || listSeqMatches(d.Author, q) {
		return true
	}
	if listSeqMatches(d.Editor, q) || matrixSeqMatchesCol(d.Lang, q, -1) {
		return true
	}
	return matrixSeqMatchesCol(d.Script, q, -1)
}
