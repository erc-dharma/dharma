"""Internal transformations.

This fixes various things in the internal XML representation (like the location
of milestones), straightens things out, and produces three displays: physical,
logical, full. Among other things, we remove all non-significant space from the
input tree.

TODO

xxx can't just transfer spaces outside of views, do something more sensible. No,
too messy, should just apply space normalization after we've expanded
everything. But need to make sure that we don't rely on space normalization in
preceding operations. This concerns:

	fix_milestones(t)
	number_notes(t)
	# And create the three displays.
	if (edition := t.first("/document/edition")):
		assert isinstance(edition, tree.Tag)
		process_edition(t, edition)

display of <am> <ex> in logical/physical/full?

we have a switch on fw in the patching code, don't do that

---

for milestones, should keep a @n, but only a @n that is unique across the whole
file (and that we thus need to preconstruct in some cases). should ensure the
uniqueness of @n across both npage and nline; ncell need not be numbered. (we
can't tell in advance whether @n is unique across the whole file or across the
textpart, so, after gathering all milestones, first check if they are unique
across the whole file. if so, keep their @n as-is. otherwise, prefix the page
number to the @n of nlines and check if unique. if so, stop there. otherwise,
invent unique @n for each milestone.)

make a root div without a @type or with an unknown type an anonymous division.

should have an axis for "everything except <note>", because there are a #
lots of cases where we _must_ avoid <note>, and it's not immediately clear #
where, and it's error-prone.
"""

import re, sys
from dharma import tree, common, languages, query_bits

def fix_search(t: tree.Tree):
	for node in t.find(".//search"):
		assert isinstance(node, tree.Tag)
		segs = query_bits.extract_text(node)
		text = "".join(str(s) for s in segs)
		node.clear()
		node.append(text)

########################## Language extraction #################################

def extract_edition_languages(root: tree.Branch):
	"""Produces two maps of the form...

		{lang: {script, script...}, lang: {script, script...}...}
		{script: {lang, lang...}, script: {lang, lang...}...}
	"""
	langs = {}
	scripts = set()
	for node in root.find("descendant-or-self::*[@lang]"):
		assert isinstance(node, tree.Tag)
		lang, script = node["lang"].split()
		langs.setdefault(lang, set()).add(script)
		scripts.add(script)
	# Filter out non-source languages and scripts.
	db = common.db("texts")
	ignore_langs = []
	lang_names = {}
	for lang in langs:
		rid, name = db.execute("""select rid, name
		from langs_list where id = ?""", (lang,)).fetchone()
		src = db.execute("""select 1 from langs_closure
		where root = (select rid from langs_list where id = 'source')
		and rid = ?""", (rid,)).fetchone()
		if src:
			lang_names[lang] = name
		else:
			ignore_langs.append(lang)
	ignore_scripts = []
	script_names = {}
	for script in scripts:
		rid, name = db.execute("""select rid, name
		from scripts_list where id = ?""", (script,)).fetchone()
		src = db.execute("""select 1 from scripts_closure
		where root = (select rid from scripts_list where id = 'source')
		and rid = ?""", (rid,)).fetchone()
		if src:
			script_names[script] = name
		else:
			ignore_scripts.append(script)
	for lang in ignore_langs:
		del langs[lang]
	for lang, lang_scripts in langs.items():
		for script in ignore_scripts:
			lang_scripts.discard(script)
	# And invert the langs map.
	scripts = {}
	for lang, lang_scripts in langs.items():
		for script in lang_scripts:
			scripts.setdefault(script, set()).add(lang)
	return langs, scripts, lang_names, script_names

def add_edition_languages(t):
	"""Add language and script use info to the tree. Need to create a
	structure like this:

	<document>
	        <languages>
	                <language>
	                        <identifier>san</identifier>
	                        <name>Sanskrit</name>
				<script>
	                                <identifier>grantha</identifier>
	                                <name>Grantha</name>
	                        </script>
				<script>
	                                <identifier>tamil</identifier>
	                                <name>Tamil</name>
	                        </script>
                        </language>
			...
	        </languages>
	        <scripts>
	                <script>
	                        <identifier>grantha</identifier>
	                        <name>Grantha</name>
				<language>
	                                <identifier>tam</identifier>
	                                <name>Tamil</name>
	                        </language>
				<language>
	                                <identifier>san</identifier>
	                                <name>Sanskrit</name>
	                        </language>
                        </script>
			...
	        </scripts>
	</document>

	Or maybe it would be better to write a generic serialization function if
	we need to use maps, etc. for something else.
	"""
	langs, scripts, lang_names, script_names = extract_edition_languages(t)
	lang_nodes = {}
	for lang in langs:
		node = tree.Tag("language")
		lang_id = tree.Tag("identifier", lang="ident latin")
		lang_id.append(lang)
		node.append(lang_id)
		lang_name = tree.Tag("name", lang="eng latin")
		lang_name.append(lang_names[lang])
		node.append(lang_name)
		lang_nodes[lang] = node
	script_nodes = {}
	for script in scripts:
		node = tree.Tag("script")
		script_id = tree.Tag("identifier", lang="ident latin")
		script_id.append(script)
		node.append(script_id)
		script_name = tree.Tag("name", lang="eng latin")
		script_name.append(script_names[script])
		node.append(script_name)
		script_nodes[script] = node
	langs_root = tree.Tag("languages")
	for lang, lang_scripts in sorted(langs.items()):
		root = lang_nodes[lang].copy()
		for script in sorted(lang_scripts):
			root.append(script_nodes[script].copy())
		langs_root.append(root)
	scripts_root = tree.Tag("scripts")
	for script, script_langs in sorted(scripts.items()):
		root = script_nodes[script].copy()
		for lang in sorted(script_langs):
			root.append(lang_nodes[lang].copy())
		scripts_root.append(root)
	t.root.prepend(scripts_root)
	t.root.prepend(langs_root)

def fix_languages(t):
	"""Set a @lang attribute on all elements."""
	languages.complete_internal(t)

########## Normalization of whitespace + removal of empty elements #############

def fix_spaces(doc: tree.Tree):
	"""Whitespace normalization and removal of empty elements.

	There are three cases.

	We remove spaces at the beginning and at the end of all elements that
	are not inline ones. After this, non-inline elements neither start with
	a space nor end with one. Furthermore, we squeeze spaces (collapse
	sequences of spaces into a single space ' ' within each element).

	If the element is an inline, we transfer spaces at the beginning and at
	the end of the subtree to the parent element, recursively. Thus,

	        <para>foo<span><link> bar</link></span></para>

	... is turned into:

	        <para>foo <span><link>bar</link></span></para>

	We drop all spaces before <note> elements (because there should be no
	space between a footnote marker and the preceding text).
	For all other tags, we drop spaces both before and after them.

	Finally, we delete all empty elements except the tree's root viz.
	<document> and milestones (<npage>, <nline>, <ncell>).
	"""
	fix_spaces_in_element(doc.root)

def fix_spaces_in_element(root: tree.Tag):
	# We need to process subtrees first: spaces might pop up from them.
	nodes = []
	for node in root:
		if isinstance(node, tree.Tag):
			nodes.append(node)
	for node in nodes:
		fix_spaces_in_element(node)
	root.coalesce(recursive=False)
	# Now we can process strings.
	nodes.clear()
	for node in root:
		if isinstance(node, (tree.Tag, tree.String)):
			nodes.append(node)
	adjust_spaces(root, nodes)
	delete_if_empty(root)

def should_trim_before(name):
	"Whether we should delete spaces before the given element."
	return name not in ("span", "link", "display", "split", "views")

def should_trim_after(name):
	"Like `should_trim_before()`, but for spaces after the given element."
	return name not in ("span", "link", "display", "split", "views", "note")

def bubble_up_start_spaces(name):
	"""If true, spaces at the beginning of this element should be moved up
	the tree, otherwise they should just be removed. For instance, if we
	have `<para>foo<span> bar</span></para>` and
	`bubble_up_start_spaces("span")` is true, the output will be `<para>foo
	<span>bar</span></para>`; but if `bubble_up_start_spaces("span")` is
	false, the output will be `<para>foo<span>bar</span></para>`.
	"""
	return name in ("span", "link", "display", "split")

def bubble_up_end_spaces(name):
	"""Like `bubble_up_start_spaces()`, but for spaces at the end of this
	element."""
	return bubble_up_start_spaces(name)

def adjust_spaces(root, nodes):
	for i, node in enumerate(nodes):
		if not isinstance(node, tree.String):
			continue
		repl = squeeze(node.data)
		assert len(repl) > 0
		if i < len(nodes) - 1 and repl and repl[-1] == " " \
			and isinstance(nodes[i + 1], tree.Tag) \
			and should_trim_before(nodes[i + 1].name):
			repl = repl.rstrip()
		if i > 0 and repl and repl[0] == " " \
			and isinstance(nodes[i - 1], tree.Tag) \
			and should_trim_after(nodes[i - 1].name):
			repl = repl.lstrip()
		if i == 0 and repl and repl[0] == " ":
			repl = repl.lstrip()
			if bubble_up_start_spaces(root.name):
				add_space_before(root)
		if i == len(nodes) - 1 and repl and repl[-1] == " ":
			repl = repl.rstrip()
			if bubble_up_end_spaces(root.name):
				add_space_after(root)
		if not repl:
			node.delete()
		elif repl != node.data:
			node.replace_with(repl)

def add_space_before(root: tree.Tag):
	"""Adds a space character right before a given node. If there is already
	one, this does nothing."""
	parent = root.parent
	assert parent is not None
	i = parent.index(root)
	if i > 0 and isinstance(parent[i - 1], tree.String):
		node = parent[i - 1]
		if len(node) > 0 and node[-1].isspace():
			# We have 'foo <root>', do nothing.
			pass
		else:
			# We have 'foo<root>', transform it to 'foo <root>'
			node.replace_with(node.data + " ")
	else:
		# We have '<foo><root>', transform it to '<foo> <root>'
		parent.insert(i, " ")

def add_space_after(root: tree.Tag):
	"""Like `add_space_before()`, but inserts a space after the node
	instead."""
	parent = root.parent
	assert parent is not None
	i = parent.index(root)
	if i < len(parent) - 1 and isinstance(parent[i + 1], tree.String):
		node = parent[i + 1]
		if len(node) > 0 and node[0].isspace():
			# We have '<root> foo', do nothing.
			pass
		else:
			# We have '<root>foo', transform it to '<root> foo'
			node.replace_with(" " + node.data)
	else:
		# We have '<root> <foo>', transform it to '<root> <foo>'
		parent.insert(i + 1, " ")

def delete_if_empty(root: tree.Tag):
	"""Deletes empty elements recursively, starting at the given one, and
	including the given one.

	Divisions that have a heading but no contents are also considered empty.
	We do not try to distinguish "default" headings (like "Apparatus", etc.)
	from non-default ones. Not sure how this should be made to work, because
	for <translation> we have several variations of "default" headings.

	`<verse>` follows the same treatment: if a verse only has a
	`<head>`, we delete it.

	Some elements are not deleted, even if they are empty. This includes
	the document's root, `<document>` (otherwise, the output wouldn't be a
	proper XML document), and a few others.
	"""
	if len(root) == 0:
		if root.name not in ("document", "npage", "nline", "ncell",
			"key", "value", "search"):
			root.delete()
	elif len(root) == 1 and isinstance(root[0], tree.Tag) and \
		root[0].name == "head":
		root.delete()

def squeeze(s):
	return re.sub(r"\s+", " ", s)


################################ Milestones ####################################

def check_milestones_valid(t, milestones):
	if __debug__:
		tmp = significant_milestones(t)
		tmpl = [id(x) for x in tmp]
		for x in milestones:
			if not id(x) in tmpl:
				print(x.xml())
		assert len(milestones) == len(tmp)
		for i, (m, n) in enumerate(zip(milestones, tmp)):
			if m is not n:
				print(f"diff at {i}", file=sys.stderr)
				print(milestones[i].xml(), file=sys.stderr)
				print(tmp[i].xml(), file=sys.stderr)
				print([x.xml() for x in milestones], file=sys.stderr)
				print([x.xml() for x in tmp], file=sys.stderr)
				raise Exception

def fix_milestones(t):
	"""The point of these transformations (besides display-related stuff)
	is to ensure all editions have the same milestones structure.

	After transforms, we have a hierarchy: page > line > cell, where each
	inscription that has an edition has 1+ page(s); where each page contains
	1+ line(s); and where each line contains 1+ cell(s). Thus, each
	inscription that has an edition contains at least three milestones: one
	page, one line, one cell. We add "phantom" (invisible) pages, lines and
	cells as needed to cover the whole text. "Phantom" milestones have an
	attribute @phantom='true', all other milestones have @phantom='false'.
	"""
	milestones = significant_milestones(t)
	# Make sure all milestones have a @phantom and a @break.
	significants = set(milestones)
	for mile in t.find(".//*[name()='npage' or name()='nline' or name()='ncell']"):
		if not mile["break"]:
			mile["break"] = "true"
		mile["phantom"] = "false"
		mile["significant"] = mile in significants and "true" or "false"
	if not milestones:
		return
	fix_milestones_location(t, milestones)
	check_milestones_valid(t, milestones)
	add_phantom_milestones(t, milestones)
	check_milestones_valid(t, milestones)
	add_milestones_breaks(t, milestones)
	check_milestones_valid(t, milestones)

def significant_milestones(t: tree.Tree):
	"""Enumerates significant milestones.

	A milestone is significant if it occurs within the edition division and
	if it is not a descendant of a "note" or "head" element. We expect to
	use significant milestones for search, and we also use them for
	generating the 3 displays of the edition division. Other,
	non-significant milestones are displayed inline and are not interpreted
	at all.
	"""
	def inner(root, out):
		for node in root:
			if not isinstance(node, tree.Tag):
				continue
			match node.name:
				case "note" | "head":
					continue
				case "npage" | "nline" | "ncell":
					out.append(node)
				case _:
					inner(node, out)
	out = []
	if (root := t.first("/document/edition")):
		inner(root, out)
	return out

# Elements within which a milestone can appear. Note that these should *not*
# overlap.
milestone_accepting = ("para", "verse-line")

def in_milestone_accepting(node):
	while True:
		parent = node.parent
		if not isinstance(parent, tree.Tag):
			return False
		if parent.name in ("span", "link"):
			node = parent
			continue
		if parent.name in milestone_accepting:
			return True
		return False

def fix_milestone_location(mile: tree.Tag):
	parent = mile.parent
	assert isinstance(parent, tree.Tag)
	match parent.name:
		case "para" | "verse-line" | "span" | "link":
			return
		case "key" | "value" | "item" | "quote":
			shift_milestones_to_nearby_block(mile)
		case "summary" | "hand" | "edition" | "apparatus" \
			| "translation" | "commentary" | "bibliography" | "div":
			tmp = tree.Tag("para", lang=parent["lang"])
			mile.insert_after(tmp)
			tmp.append(mile)
		case "verse":
			shift_milestones_in_verse(mile)
		case "elist":
			shift_milestones_in_elist(mile)
		case "dlist":
			shift_milestones_in_dlist(mile)
		case _:
			sys.stdout.write(mile.tree.xml())
			raise Exception(f"unexpected: milestone {mile!r} parent {mile.parent!r}")
	return fix_milestone_location(mile)

def fix_milestones_location(t, milestones):
	"""Move milestones in appropriate spots.

        If the milestone appears at the beginning or at the end of an inline
        element (span or link), we move the milestone outside of this element.

        before or after (respectively) the parent element,
           and repeat as much as possible, stopping as soon as the parent is a
           milestone-accepting element. Milestones should only appear within one
           of these. In practice, we should only move up from inline elements,
           but this must be checked. Probably simpler to move it up only while
           the parent is an inline element *and* while the milestone is at the
           beginning/end of this inline.

        Problem: moving things up would not work properly if we do some
        transformations on the contents (add a prefix or suffix), as in:

                <supplied><lb n="1"/>foo</supplied>

                <span class="supplied" tip="Lost text">[<nline
                break="true"><span tip="Line
                number">⟨1⟩</span></nline>foo]</span>

        To fix this, we wrap the added contents within <display> and treat this
        tag as empty while moving up the milestone, thus:

                <supplied><lb n="1"/>foo</supplied>

                ... results in:

                <span class="supplied" tip="Lost
                text"><display>[</display><nline break="true"><span tip="Line
                number">⟨1⟩</span></nline><span>foo</span><display>]</display></span>

                ... which results in:

                <nline break="true"><span tip="Line
                number">⟨1⟩</span></nline><span class="supplied" tip="Lost
                text"><display>[</display><span>foo</span><display>]</display></span>

        Another (maybe preferable) solution would be to leave the displayed
        milestone in place and move up only a structural element (which would
        not be displayed).

        2) If the milestone is not within one of the milestone-accepting
           elements, move it forward to the beginning of the next
           milestone-accepting element (in following::* order) (but skip <note>
           and its descendants). Exception if the milestone appears at the very
           end of the edition: in this case, leave it where it is. But what if
           the milestone is outside of a <p>?

        What about consecutive npages, etc.? We need to create an extra <p> for
        them, but we should do this only when rendering the physical display.

                <para> <span> A <span><npage/>B</span> C </span> </para>

                <para> A <span> B <npage/> </span> </para>

        moving up milestones must be done in a definite order, in two passes.
        iter milestones and move them up from left to right (for start) and the
        reverse (for end), then proceed with the upper level. if we end up in a
        non-inline, we should be within some kind of division; move the
        milestone forward if possible, otherwise move it backward, otherwise
        create a <p> at this location (and this <p> should be the only p within
        the edityion)
	"""
	milestones_set = set(milestones)
	move_up_milestones(t.root, milestones_set)
	check_milestones_valid(t, milestones)
	# Milestones that are not in a milestone-accepting element. If the
	# milestone's parent is a division, wrap the milestone within a <p>.
	# XXX not enough, need to do that with other elements.
	for mile in milestones:
		fix_milestone_location(mile)

def is_milestone(node):
	if not isinstance(node, tree.Tag):
		return False
	return node.name in ("npage", "nline", "ncell")

def shift_milestones(parent, skip):
	# Move all milestones at the end of parent to the end of the last
	# container in parent
	k = len(parent)
	while k > skip:
		k -= 1
		if not is_milestone(parent[k]):
			break
	else:
		# "parent" should contain at least one container where we can
		# stick milestones.
		raise Exception
	where = parent[k]
	k += 1
	while k < len(parent):
		where.append(parent[k])
	# Move remaining milestones to the start of the following container.
	k = skip
	while k < len(parent):
		if is_milestone(parent[k]):
			k += 1
			continue
		where = parent[k]
		while k > skip:
			k -= 1
			if not is_milestone(parent[k]):
				break
			where.prepend(parent[k])
		k += 2

def shift_milestones_to_nearby_block(mile: tree.Tag):
	parent = mile.parent
	assert isinstance(parent, tree.Tag)
	shift_milestones(parent, 0)

def shift_milestones_in_verse(mile: tree.Tag):
	parent = mile.parent
	assert isinstance(parent, tree.Tag)
	assert all(isinstance(elem, tree.Tag) for elem in parent)
	# We should have at least one <verse-line>, for holding the milestone.
	# If there is none, create one.
	if not any(elem.name == "verse-line" for elem in parent):
		parent.append(tree.Tag("verse-line", lang=parent["lang"]))
	# Skip the heading, if any. Besides it, should only have as children
	# either milestones or verse-line.
	if parent[0].name == "head":
		skip = 1
	else:
		skip = 0
	assert all(elem.name in ("npage", "nline", "ncell", "verse-line") for elem in parent[skip:]), parent.xml()
	return shift_milestones(parent, skip)

def shift_milestones_in_elist(mile):
	parent = mile.parent
	assert all(isinstance(elem, tree.Tag) for elem in parent)
	# We should have at least one <item>, for holding the milestone.
	# Create one if need be.
	if not any(elem.name == "item" for elem in parent):
		parent.append(tree.Tag("item", lang=parent["lang"]))
	assert all(elem.name in ("npage", "nline", "ncell", "item") for elem in parent)
	return shift_milestones(parent, 0)

def shift_milestones_in_dlist(mile):
	parent = mile.parent
	assert all(isinstance(elem, tree.Tag) for elem in parent)
	# We should have at least one <key>/<value> pair, for holding the
	# milestone. Create one if need be.
	if not any(elem.name == "value" for elem in parent):
		parent.append(tree.Tag("key", lang=parent["lang"]))
		parent.append(tree.Tag("value", lang=parent["lang"]))
	assert all(elem.name in ("npage", "nline", "ncell", "key", "value") for elem in parent)
	return shift_milestones(parent, 0)

def move_up_milestones(root: tree.Tag, milestones):
	assert isinstance(root, tree.Tag)
	for node in list(root):
		if not isinstance(node, tree.Tag):
			continue
		if node.name in ("npage", "nline", "ncell"):
			continue
		move_up_milestones(node, milestones)
	if root.name not in ("span", "link"):
		return
	# We have an inline element (<span> or <link>). Move all milestones
	# at the beginning of the element to before the element; thus:
	#
	# 	before: foo <span><nline/><ncell/>bar</span> baz
	#	after:  foo <nline/><ncell/><span>bar</span> baz
	#
	# Idem for milestones at the end of the inline element.
	i = 0
	while i < len(root) and isinstance(root[i], tree.Tag) and root[i].name in ("display", "views", "split"):
		i += 1
	while len(root) > i and root[i] in milestones:
		root.insert_before(root[i])
	j = len(root)
	while j > i and isinstance(root[j - 1], tree.Tag) and root[j - 1].name in ("display", "views", "split"):
		j -= 1
	while j > i and root[j - 1] in milestones:
		root.insert_after(root[j - 1])
		j -= 1

def first_milestone_accepting_node(doc):
	def inner(root):
		for node in root:
			if not isinstance(node, tree.Tag):
				continue
			if node.name in milestone_accepting:
				return node
			ret = inner(node)
			if ret:
				return ret
	root = doc.first("/document/edition")
	assert root
	ret = inner(root)
	assert ret
	return ret

def phantom_milestone(type: str):
	assert type in ("npage", "nline", "ncell")
	return tree.Tag(type, break_="true", phantom="true", significant="true")

def add_phantom_milestones(doc: tree.Tree, milestones):
	"""Allocate phantom milestones to fill up the edition.

	We have to allocate phantom pages/lines/cells, when (a) the encoding is
	incorrect; or (b) the encoding is correct but a category is missing. It
	is best to keep these phantom elements in the output than to remove
	them, for search.

	we can't really tell whether numbering is continuous between textparts
	or not, so if we have:

	        <pb n=X>foo<div type="textpart">bar<pb n=Z>

	we assume that page X continues in the next textpart (instead of
	assuming that the next textpart is missing a <pb n=Y> at the very
	beginning). to represent the fact that page X continues in the next
	textpart, use a cont=true flag in the first div we generate within the
	next textpart.

	when generating the search representation, not sure what to do with the
	textpart heading in the middle. might want to index separately the TOC
	(with all headings) and the text (without interruption).
	"""
	insert = first_milestone_accepting_node(doc)
	i = 0
	units = ("npage", "nline", "ncell")
	while i < 3:
		unit = units[i]
		if len(insert) > i and isinstance(insert[i], tree.Tag) and insert[i].name == unit:
			assert len(milestones) > i
			assert insert[i] is milestones[i]
		else:
			mile = phantom_milestone(unit)
			insert.insert(i, mile)
			milestones.insert(i, mile)
		i += 1
	assert i == 3
	while i < len(milestones):
		mile = milestones[i]
		if mile.name == "npage":
			if (tmp := mile.first("following-sibling::*")) and tmp.name == "nline":
				mile = tmp
			else:
				tmp = phantom_milestone("nline")
				mile.insert_after(tmp)
				mile = tmp
				milestones.insert(i + 1, tmp)
			if (tmp := mile.first("following-sibling::*")) and tmp.name == "ncell":
				mile = tmp
			else:
				tmp = phantom_milestone("ncell")
				mile.insert_after(tmp)
				mile = tmp
				milestones.insert(i + 2, tmp)
			i += 3
		elif mile.name == "nline":
			if (tmp := mile.first("following-sibling::*")) and tmp.name == "ncell":
				pass
			else:
				tmp = phantom_milestone("ncell")
				mile.insert_after(tmp)
				milestones.insert(i + 1, tmp)
			i += 2
		elif mile.name == "ncell":
			i += 1
		else:
			raise Exception

def add_milestones_breaks(doc, milestones):
	"""Add missing @break to each milestone and make @break consistent.

	The following rules are observed.

	The 3 initial milestones (at the very beginning of the first
	milestone-accepting element) must have @break="yes".

	The last ncell in the edition must have @break="yes". Idem for the
	preceding nline and npage if they appear right before the ncell, without
	any text or other tag in-between.

	In all other cases, we must necessarily have homogeneous values for
	@break in sequences of the forms <npage><nline><ncell> or
	<nline><ncell>. If a milestone in such a sequence has @break="false", it
	is because @break was explicitly given in the original TEI (per contrast
	with @break="true", because "true" is the default value). We thus assume
	that the author does mean @break="false" for adjacent milestones, too,
	and thus we set @break="false" for these as well.
	"""
	assert len(milestones) >= 3
	assert milestones[0].name == "npage"
	assert milestones[1].name == "nline"
	assert milestones[2].name == "ncell"
	for mile in milestones[:3]:
		mile["break"] = "true"
	miles = iter(milestones[3:])
	for mile in miles:
		if mile.name == "npage":
			tmp = [mile, next(miles), next(miles)]
			assert tmp[1].name == "nline"
			assert tmp[2].name == "ncell"
			if all(mile["break"] == "true" for mile in tmp):
				pass
			else:
				for mile in tmp:
					mile["break"] = "false"
		elif mile.name == "nline":
			tmp = [mile, next(miles)]
			assert tmp[1].name == "ncell"
			if all(mile["break"] == "true" for mile in tmp):
				pass
			else:
				for mile in tmp:
					mile["break"] = "false"
		elif mile.name == "ncell":
			pass
		else:
			raise Exception
	cell = milestones[-1]
	if milestone_is_terminal(doc, cell):
		cell["break"] = "true"
		if (line := cell.first("stuck-preceding-sibling::nline")):
			line["break"] = "true"
			if (page := line.first("stuck-preceding-sibling::npage")):
				page["break"] = "true"

def milestone_is_terminal(doc, mile):
	"""Whether this milestone (which must be a cell) occurs at the very end
	of the text"""
	assert mile.name == "ncell"
	last = None
	for node in doc.find("//*"):
		if node.name not in milestone_accepting:
			continue
		last = node
	return last is mile

def milestone_at_block_start(node):
	while True:
		parent = node.parent
		assert isinstance(parent, tree.Tag)
		i = parent.index(node)
		if i > 0:
			return False
		if parent.name not in ("span", "link"):
			return True
		node = parent

def milestone_at_block_end(node):
	while True:
		parent = node.parent
		assert isinstance(parent, tree.Tag)
		i = parent.index(node)
		if i < len(parent) - 1:
			return False
		if parent.name not in ("span", "link"):
			return True
		node = parent

def fix_milestones_spaces(t: tree.Branch, physical=False):
	"""Adds spaces around milestones, where needed. If physical is False,
	only adds spaces if @break=true; otherwise, take all milestones into
	account.

	This is only performed for milestones that have a @break that matches
	the boolean given as argument. (For the logical and full display, we
	only apply add spaces when @break=true, while for the physical display
	we add spaces for all values of @break.)
	"""
	# Note that @phantom milestones must be excluded (we don't
	# actually display them). Also note that we replace all milestones,
	# even the ones in the apparatus.
	for node in t.find(".//*[(name()='npage' or name()='nline' or name()='ncell') and not @phantom='true']"):
		assert isinstance(node, tree.Tag) # silence warnings
		if physical:
			# There is exactly one case in which we must not add
			# any spaces: ncell[@break="no"]
			if node.name == "ncell" and not common.to_boolean(node["break"], True):
				continue
		else:
			if not common.to_boolean(node["break"], True):
				continue
		if not milestone_at_block_start(node):
			node.prepend(" ")
		if not milestone_at_block_end(node):
			node.append(" ")


########################### Physical Display ###################################

# XXX TODO for physical:
# wrap lines within <para>
# split these elements if needed: a, para

def unwrap_for_physical(root: tree.Node):
	"""Unwraps or deletes tags that are not necessary for the physical
	display.
	"""
	for node in list(root):
		if not isinstance(node, tree.Tag):
			continue
		match node.name:
			case "note":
				# No recursion here, the node is part of the
				# text.
				pass
			case "display":
				unwrap_for_physical(node)
				node.unwrap()
			case "split":
				display = node.first("display")
				assert display
				unwrap_for_physical(display)
			case "views":
				# We deal with this elsewhere.
				pass
			case "div" | "head" | "span" | "link" | "npage" | "nline" | "ncell":
				unwrap_for_physical(node)
			case "dlist" | "elist" | "quote" | "key" | "value" | "item":
				unwrap_for_physical(node)
				node.unwrap()
			case "verse":
				if (head := node.first("stuck-child::head")):
					head.delete()
				unwrap_for_physical(node)
				node.unwrap()
			case "source":
				node.delete()
			case "para":
				unwrap_for_physical(node)
				node.prepend(" ")
				node.unwrap()
			case "verse-line":
				unwrap_for_physical(node)
				if common.to_boolean(node["break"]):
					node.prepend(" ")
				node.unwrap()
			case _:
				raise Exception(f"unexpected: {node!r}")

# People often use div[@type='textpart'] instead of page-like milestones for
# indicating physical divisions. We thus have a lot of inscriptions that
# have two textparts "Seal" and "Plates". In such cases, a new textpart means
# a new page-like division. But people also use textparts independently of
# page-like milestones. We can't tell what the user means, so do nothing
# special for now.
def wrap_for_physical(root, page=None, line=None):
	for node in list(root):
		if not isinstance(node, tree.Tag):
			if not page:
				page = tree.Tag("page", lang=root["lang"])
				node.insert_before(page)
			if not line:
				line = tree.Tag("line", lang=root["lang"])
				page.append(line)
			line.append(node)
			continue
		match node.name:
			case "div":
				page = line = None
				wrap_for_physical(node, page, line)
			case "head":
				page = line = None
			case "npage":
				page = tree.Tag("page", lang=root["lang"])
				node.insert_before(page)
				head = tree.Tag("head", lang="zxx latin")
				head.append(node)
				page.append(head)
				line = None
			case "nline":
				if not page:
					page = tree.Tag("page", lang="zxx latin")
					node.insert_before(page)
				line = tree.Tag("line", lang=root["lang"])
				page.append(line)
				line.append(node)
			case "ncell" | "span" | "link" | "note" | "views" | "split":
				if not page:
					page = tree.Tag("page", lang=root["lang"])
					node.insert_before(page)
				if not line:
					line = tree.Tag("line", lang=root["lang"])
					page.append(line)
				line.append(node)
			case _:
				raise Exception(f"unexpected: {node!r}")

# XXX in physical, differenciate between continuation lines and others?
# yes, a continuation page/line/cell is one that meets all following criteria:
# 1) appears at the beginning of a division
# 2) a milestone we generated viz. that the user did not specifify
# 3) is not the first npage/nline/ncell in the <edition>
# it is only created in wrap-for-physical, so do necessary stuff here.

def add_hyphens_to_lines(t):
	# We need to add a hyphen break after all the milestone @break=no,
	# whether or not there is a hyphen break at the end of the line.
	# (We also have preceding hyphens sometimes, but this is not OK I
	# think.)
	# Use <display><span tip="Hyphen break">-</span> at the end of each
	# line
	# Exclude phantom lines because we sometimes have:
	# foo<pb n="1" break="no"/><pb n="2" break="no"/>bar
	# In this case, we must add a hyphen after "foo", but in the phantom
	# line between pages 1 and 2.
	lines = t.find(".//line[not stuck-child::nline[@phantom='true']]")
	i = 1
	while i < len(lines):
		head = lines[i][0]
		if not isinstance(head, tree.Tag) or not head.name == "nline":
			i += 1
			continue
		if not common.to_boolean(head["break"], True):
			span = tree.Tag("span", tip="Hyphen break", lang="zxx latin")
			span.append("-")
			lines[i - 1].append(span)
		i += 1

def split_around_milestone(inline, mile):
	"""We only perform a split on the first milestone. Thus, if there are
	several same-level milestones in a single span, this only takes into
	account the one given as argument (and the line/cell that immediately
	follow).
	"""
	left = None
	stack = []
	line = cell = None
	def inner(root):
		nonlocal left, stack, line, cell
		stack.append(tree.Tag(root.name, **root.attrs))
		i = 0
		while i < len(root):
			elem = root[i]
			if not isinstance(elem, tree.Tag):
				stack[-1].append(elem.copy())
				i += 1
				continue
			if elem is not mile:
				elem = inner(elem)
				stack[-1].append(elem)
				i += 1
				continue
			if mile.name == "npage":
				assert i < len(root) - 2 \
					and isinstance(root[i + 1], tree.Tag) \
					and root[i + 1].name == "nline" \
					and isinstance(root[i + 2], tree.Tag) \
					and root[i + 2].name == "ncell"
				line = root[i + 1]
				cell = root[i + 2]
				i += 3
			else:
				assert mile.name == "nline"
				assert i < len(root) - 1 \
					and isinstance(root[i + 1], tree.Tag) \
					and root[i + 1].name == "ncell"
				cell = root[i + 1]
				i += 2
			new_stack = []
			for tag in stack:
				new_stack.append(tree.Tag(tag.name, **tag.attrs))
			while len(stack) > 1:
				tag = stack.pop()
				stack[-1].append(tag)
			left = stack.pop()
			stack = new_stack
		return stack.pop()
	right = inner(inline)
	assert left
	assert mile.name == "npage" and line or line is None
	assert cell
	inline.insert_before(left)
	if mile.name == "npage":
		left.insert_after(mile)
		assert line
		mile.insert_after(line)
		line.insert_after(cell)
	else:
		assert mile.name == "nline"
		left.insert_after(mile)
		mile.insert_after(cell)
	cell.insert_after(right)
	inline.delete()

def fix_physical_inlines(t):
	milestones = t.find(".//*[@significant and (name()='npage' or name()='nline' or name()='ncell')]")
	for mile in milestones:
		if mile.name == "ncell":
			# Cells should remain inlines
			continue
		inline = mile.parent
		if inline.name not in ("span", "link"):
			continue
		while True:
			parent = inline.parent
			if isinstance(parent, tree.Tag) and parent.name in ("span", "link"):
				inline = parent
			else:
				break
		split_around_milestone(inline, mile)

def to_physical(t):
	unwrap_for_physical(t)
	fix_spaces(t)
	fix_physical_inlines(t)
	wrap_for_physical(t)
	fix_milestones_spaces(t, physical=True)
	add_hyphens_to_lines(t)
	for node in t.find(".//span[@class='corr' and @standalone='false']"):
		node.delete()
	for node in t.find(".//span[@class='reg' and @standalone='false']"):
		node.delete()

def complete_verse_lines(t: tree.Tree):
	"""Add a hyphen before verse-line elements that have @break='false', and
	add a @break='true' attribute to all the others."""
	for line in t.find(".//verse-line"):
		assert isinstance(line, tree.Tag)
		if common.to_boolean(line["break"], True):
			line["break"] = "true"
			continue
		prev_line = line.first("stuck-preceding-sibling::*")
		assert isinstance(prev_line, tree.Tag)
		assert prev_line.name == "verse-line"
		span = tree.Tag("span", tip="Hyphen break", lang="zxx latin")
		span.append("-")
		prev_line.append(span)

def to_logical(t):
	for node in t.find(".//span[@class='sic' and @standalone='false']"):
		node.delete()
	for node in t.find(".//span[@class='orig' and @standalone='false']"):
		node.delete()

def number_notes(t: tree.Tree):
	"""We number notes before we create the three displays, to make it
	easier later on to figure out which notes are duplicates."""
	notes = t.find(".//note", sort=True)
	for i, note in enumerate(notes, 1):
		assert isinstance(note, tree.Tag)
		note["n"] = str(i)

def is_inline(node):
	if isinstance(node, tree.String):
		return True
	if not isinstance(node, tree.Tag):
		return False
	return node.name in ("span", "link", "note", "npage", "nline", "ncell",
		"display", "views", "split")

def cover_inlines_with_paras(root):
	i = 0
	while i < len(root):
		if not is_inline(root[i]):
			i += 1
			continue
		j = i + 1
		while j < len(root) and is_inline(root[j]):
			j += 1
		para = tree.Tag("para", lang=root["lang"])
		para.extend(root[i:j])
		root.insert(i, para)
		i += 1

def cover_inlines_with_verse_lines(root):
	i = 0
	while i < len(root):
		if not is_inline(root[i]) or is_milestone(root[i]):
			i += 1
			continue
		j = i + 1
		while j < len(root) and is_inline(root[j]) and not is_milestone(root[j]):
			j += 1
		para = tree.Tag("verse-line", lang=root["lang"])
		para.extend(root[i:j])
		root.insert(i, para)
		i += 1

def wrap_inlines_in_paragraphs(root):
	"Wraps within paragraphs inline children of divisions-like elements."
	for node in root:
		if not isinstance(node, tree.Tag):
			continue
		if node.name in ("summary", "hand", "note", "edition",
			"apparatus", "translation", "commentary",
			"bibliography", "div", "item", "key", "value", "quote"):
			cover_inlines_with_paras(node)
		elif node.name == "verse":
			cover_inlines_with_verse_lines(node)
		wrap_inlines_in_paragraphs(node)

def add_phantom_divisions(root: tree.Branch):
	"Wraps within divisions isolated paragraphs."
	for node in root:
		if not isinstance(node, tree.Tag):
			continue
		if node.name == "div":
			node["phantom"] = "false"
		if node.name in ("edition", "apparatus", "translation",
			"commentary", "bibliography", "div"):
			cover_contents_with_div(node)
		add_phantom_divisions(node)

def contains_div(root):
	for child in root:
		match child:
			case tree.Tag("div"):
				return True
	return False

def cover_contents_with_div(root: tree.Tag):
	if not contains_div(root):
		return
	cur_div = None
	for node in list(root):
		match node:
			case tree.String():
				assert node.isspace()
				continue
			case tree.Tag():
				pass
			case tree.Comment():
				continue
			case _:
				raise Exception(f"unexpected {node!r}")
		match node.name:
			case "para" | "quote" | "verse" | "dlist" | "elist":
				if cur_div is None:
					cur_div = tree.Tag("div", phantom="true")
					node.insert_before(cur_div)
				cur_div.append(node)
			case "div":
				cur_div = None
			case "head":
				pass
			case _:
				raise Exception(f"unexpected {node!r}")

# XXX need more stuff for parsing <verse>, not sure we're exhaustive.

def fix_blocks_nesting(t: tree.Tree):
	"""Fix most blocks nesting problems. If people followed the guide, these
	should not arise.

	We have a nesting problem if an inline element contains some kind of
	block, or if para or verse-line contains a block (TODO other elements
	are concerned). When we end up in this situation, we unwrap the inner
	block element. This is probably the most sensible approach; we could
	also do the reverse viz. unwrap the outer inline or block element, but
	this looks less clean.
	"""
	def inner(root):
		assert isinstance(root, tree.Tag)
		if is_inline(root) or root.name in ("para", "verse", "verse-line"):
			unwrap_child_blocks(root)
		for child in root:
			if isinstance(child, tree.Tag):
				inner(child)
	inner(t.root)

def unwrap_child_blocks(root: tree.Tag):
	"""Unwraps block elements that are children of the given element, and
	unwraps or deletes as well their inner structural elements (source, key,
	value, item...).
	"""
	i = 0
	while i < len(root):
		node = root[i]
		if not isinstance(node, tree.Tag):
			i += 1
			continue
		match node.name:
			case "div":
				head = node.first("stuck-child::head")
				if head:
					head.delete()
				node.unwrap()
			case "head" if root.name == "verse":
				i += 1
				continue
			case "para" | "head":
				node.unwrap()
			case "verse":
				head = node.first("stuck-child::head")
				if head:
					head.delete()
				for line in node.find("verse-line"):
					line.prepend(" ")
					line.append(" ")
					line.unwrap()
				node.unwrap()
			case "quote":
				head = node.first("stuck-child::source")
				if head:
					head.delete()
				node.unwrap()
			case "elist":
				for elem in node.find("item"):
					elem.prepend(" ")
					elem.append(" ")
					elem.unwrap()
				node.unwrap()
			case "dlist":
				for elem in node.find("./*[name()='key' or name='value']"):
					elem.prepend(" ")
					elem.append(" ")
					elem.unwrap()
				node.unwrap()
			case _:
				i += 1

def fix_blocks_within_paras(t: tree.Tree):
	"""The guide prescribes to wrap lists and quotes within paragraphs, but
	we do not want this in the internal representation. Most importantly,
	because this does not produce valid HTML; but also because we need a
	paragraph-like element that cannot possibly contain other paragraphs, so
	we might as well call it a paragraph.

	In the future, might want to treat differently in the display lists and
	quotes within paragraphs, on the one hand, and lists and quotes outside
	of paragraphs, on the other.
	"""
	for node in t.find(".//para/*[regex('^elist|dlist|quote$', name())]"):
		move_up_from_para(node)

def move_up_from_para(node):
	para = node.parent
	assert isinstance(para, tree.Tag) and para.name == "para"
	left = tree.Tag(para.name, **para.attrs)
	right = tree.Tag(para.name, **para.attrs)
	buf = left
	for child in list(para):
		if child is node:
			buf = right
		else:
			buf.append(child)
	if len(left) > 0:
		para.insert_before(left)
	para.replace_with(node)
	if len(right) > 0:
		node.insert_after(right)

def expand_views(root: tree.Branch, keep_view=None):
	"""Expands "views" element. They have the form:

		<views>
			<physical>X</physical>
			<logical>Y</logical>
			<full>Z</full>
		</views>

	And we end up with just X, Y or Z, depending on whether the node is a
	descendant of //edition/physical, //edition/logical or //edition/full.
	"views" nodes elsewhere in the document are treated as if they were
	under //edition/full viz. we replace them with Z.

	XXX note that the fact we expand it after the rest might prevent proper
	positioning of milestones, etc. deal with this.
	"""
	views = ("physical", "logical", "full")
	if not keep_view:
		if isinstance(root, tree.Tag) and root.name in views:
			keep = keep_view = root.name
		else:
			keep = "full"
	else:
		keep = keep_view
	for node in root.find("*"):
		assert isinstance(node, tree.Tag)
		if node.name != "views":
			expand_views(node, keep_view)
			continue
		# Note that we don't expect "views" elements to nest.
		for view in views:
			target = node.first(view)
			assert isinstance(target, tree.Tag)
			if view == keep:
				expand_views(target, keep_view)
				target.unwrap()
			else:
				target.delete()
		node.unwrap()

def process_edition(t: tree.Tree, edition: tree.Tag):
	full = edition.copy()
	full.name = "full"
	if (head := full.first("head")):
		head.delete()
	physical = full.copy()
	physical.name = "physical"
	to_physical(physical)
	fix_milestones_spaces(full)
	logical = full.copy()
	logical.name = "logical"
	to_logical(logical)
	head = edition.first("head")
	assert isinstance(edition, tree.Branch)
	edition.clear()
	fix_milestones_spaces(t)
	if head:
		edition.append(head)
	edition.append(physical)
	edition.append(logical)
	edition.append(full)

# XXX covering inlines with para or verse-line doesn't interact properly with
# milestones placement; should merge the processing code for both.

# XXX straighten out the code. the order of operations should be clear, and it
# should be possible at each step to see the output, for better debugging. maybe
# use a table of functions; and annotate all these functions with a docstring.
# also, don't really bother about redundant operations: better make it readable
# and slower than the reverse.

def process(t: tree.Tree):
	fix_search(t)
	fix_languages(t)
	# Structural stuff.
	fix_blocks_within_paras(t)
	fix_blocks_nesting(t)
	wrap_inlines_in_paragraphs(t)
	add_phantom_divisions(t)
	# Rest
	fix_spaces(t)
	fix_milestones(t)
	number_notes(t)
	# And create the three displays.
	if (edition := t.first("/document/edition")):
		assert isinstance(edition, tree.Tag)
		process_edition(t, edition)
	expand_views(t)
	for node in t.find(".//*[@significant and (name()='npage' or name()='nline' or name()='ncell')]"):
		assert isinstance(node, tree.Tag)
		del node["milestone-keep"]
	for node in t.find(".//display[@name]"):
		assert isinstance(node, tree.Tag)
		if node["name"] == "physical":
			node.delete()
		else:
			assert node["name"] == "logical"
			del node["name"]
	complete_verse_lines(t)
	# And extract languages from the logical division.
	if (root := t.first("/document/edition/logical")):
		add_edition_languages(root)
	languages.finish_internal(t)

def fetch_file_data(ident):
	db = common.db("texts")
	return db.execute("""
	select
		files.name as ident,
		repos.repo as repo_ident,
		repos.title as repo_title,
		path,
		commit_hash,
		commit_date,
		last_modified_commit as last_modified_commit_hash,
		last_modified as last_modified_commit_date,
		format_url('https://github.com/erc-dharma/%s/blob/%s/%s', repos.repo,
			commit_hash, path) as github_commit_url,
		format_url('https://github.com/erc-dharma/%s/blob/%s/%s', repos.repo,
			last_modified_commit, path)
			as github_last_modified_commit_url,
		format_url('https://raw.githubusercontent.com/erc-dharma/%s/%s/%s',
			repos.repo, commit_hash, path)
			as github_download_url
	from documents
		join files on documents.name = files.name
		join repos on documents.repo = repos.repo
	where documents.name = ?""", (ident,)).fetchone()

def add_file_info(t: tree.Tree, data: dict):
	"""Adds extra fields by fetching the necessary data from the db. This
	concerns fields that we don't infer from parsing the TEI but that we
	want to display on the website, viz. file-related data (repo, commit,
	etc.). We want to end up with:

	```
	<document>
		<identifier/>
		<repository>
			<identifier/>
			<name/>
		</repository>
		<path/>
		<commit>
			<hash/>
			<date/>
		</commit>
		<last-modified-commit>
			<hash/>
			<date/>
		</last-modified-commit>
		...
	</document>
	```
	"""
	# Last modified commit
	if data.get("last_modified_commit_hash"):
		commit = tree.Tag("last-modified-commit")
		hash_ = tree.Tag("hash")
		hash_.append(data["last_modified_commit_hash"])
		commit.append(hash_)
		date = tree.Tag("date")
		date.append(str(data["last_modified_commit_date"]))
		commit.append(date)
		t.root.prepend(commit)
	# Commit
	if data.get("commit_hash"):
		commit = tree.Tag("commit")
		hash_ = tree.Tag("hash")
		hash_.append(data["commit_hash"])
		commit.append(hash_)
		date = tree.Tag("date")
		date.append(str(data["commit_date"]))
		commit.append(date)
		t.root.prepend(commit)
	# Path
	if data.get("path"):
		path = tree.Tag("path")
		path.append(data["path"])
		t.root.prepend(path)
	# Repository
	if data.get("repo_ident"):
		repo = tree.Tag("repository")
		identifier = tree.Tag("identifier")
		identifier.append(data["repo_ident"])
		repo.append(identifier)
		name = tree.Tag("name")
		name.append(data["repo_title"])
		repo.append(name)
		t.root.prepend(repo)
	# Identifier
	if data.get("ident"):
		identifier = tree.Tag("identifier")
		identifier.append(data["ident"])
		t.root.prepend(identifier)

def make_pretty_printable(t: tree.Tree):
	t.coalesce()
	# Make spaces apparent around tags.
	for s in t.strings():
		if s[0] == " ":
			s.insert_before(tree.Comment("space"))
		if s[-1] == " " and len(s) > 1:
			s.insert_after(tree.Comment("space"))

if __name__ == "__main__":
	import os, sys
	from dharma import tei, common, texts

	@common.transaction("texts")
	def main():
		path = os.path.abspath(sys.argv[1])
		f = texts.File("/", path)
		t = tei.process_file(f).serialize()
		process(t)
		make_pretty_printable(t)
		sys.stdout.write(t.xml(add_xml_prefix=False))
	try:
		main()
	except BrokenPipeError:
		pass
