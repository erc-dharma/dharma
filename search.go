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
	titleCollator = collate.New(language.Make("en-u-ka-shifted"))
}

func (c *TransformCache) get(text, mode string) string {
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
	if sortBy == "ident" {
		return
	}
	sort.Slice(docs, func(i, j int) bool {
		return compareDocs(docs[i], docs[j], sortBy)
	})
}

func myCompareString(c *collate.Collator, a, b string) int {
	var buf collate.Buffer
	kA := c.KeyFromString(&buf, a)
	kB := c.KeyFromString(&buf, b)
	ret := bytes.Compare(kA, kB)
	buf.Reset()
	return ret
}

func compareDocs(d1, d2 Document, sortBy string) bool {
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
	results := make([]SearchResult, 0, len(docs))
	for _, doc := range docs {
		results = append(results, matchDocument(doc, q))
	}
	return results
}

func parseQuery(qStr string) QueryNode {
	var q QueryNode
	json.Unmarshal([]byte(qStr), &q)
	return q
}

func filterDocs(qStr string) []Document {
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
	for _, arg := range args {
		if !matchQuery(d, arg) {
			return false
		}
	}
	return len(args) > 0
}

func evalOr(d Document, args []QueryNode) bool {
	for _, arg := range args {
		if matchQuery(d, arg) {
			return true
		}
	}
	return len(args) > 0
}

func containsMatcher(cache *TransformCache, text, term, mode, field string) bool {
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
	if containsMatcher(d.Cache.Logical, d.Logical, val, mode, "logical") {
		return true
	}
	if containsMatcher(d.Cache.Ident, d.Ident, val, mode, "ident") {
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
	var c *TransformCache
	if rowCaches != nil && col < len(rowCaches) {
		c = rowCaches[col]
	}
	return containsMatcher(c, row[col], q, mode, field)
}

func matchDocument(doc Document, qStr string) SearchResult {
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
	q := parseQuery(qStr)
	terms := extractTerms(q)
	if len(terms) == 0 {
		return
	}
	highlightFields(res, doc, terms)
}

func highlightFields(res *SearchResult, doc Document, terms []QueryTerm) {
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
	processMatrixTermsCol(res.Lang, doc.Lang, termsForFields(terms, "lang", "lang_ident"), "lang_ident", 0)
	processMatrixTermsCol(res.Lang, doc.Lang, termsForFields(terms, "lang", "lang_name"), "lang_name", 1)
	processMatrixTermsCol(res.Script, doc.Script, termsForFields(terms, "script", "script_ident"), "script_ident", 0)
	processMatrixTermsCol(res.Script, doc.Script, termsForFields(terms, "script", "script_name"), "script_name", 1)
}

func cloneList(src []string) []string {
	dst := make([]string, len(src))
	copy(dst, src)
	return dst
}

func cloneMatrix(src [][]string) [][]string {
	dst := make([][]string, len(src))
	for i, row := range src {
		dst[i] = make([]string, len(row))
		copy(dst[i], row)
	}
	return dst
}

func processFieldTerms(target *string, source string, terms []QueryTerm, fieldName string) bool {
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
	matched := false
	for i, item := range sources {
		if processFieldTerms(&targets[i], item, terms, fieldName) {
			matched = true
		}
	}
	return matched
}

func processListTermsParity(targets []string, sources []string, terms []QueryTerm, fieldName string, parity int) bool {
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
	if mode == "" {
		if field == "logical" {
			mode = "normalized"
		} else {
			mode = "normal"
		}
	}
	mapper := func(s string) (string, []int) {
		return transformWithBounds(s, mode)
	}
	return findOccurrencesWithMapping(text, term, mapper)
}

func findOccurrencesWithMapping(text, term string, mapper StringMapper) [][2]int {
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
	var points []Point
	for _, interval := range intervals {
		points = append(points, Point{interval[0], 1})
		points = append(points, Point{interval[1], -1})
	}
	sortPoints(points)
	return points
}

func sortPoints(points []Point) {
	sort.Slice(points, func(i, j int) bool {
		if points[i].idx != points[j].idx {
			return points[i].idx < points[j].idx
		}
		return points[i].kind < points[j].kind
	})
}

func processPoint(p Point, depth int, sb *strings.Builder) int {
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
