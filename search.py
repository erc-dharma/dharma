import sys
import unicodedata
import requests
from dharma import common, tree, query
import icu
import re

# Unicode Private Use Area characters for search markers
MARKER_START = "\uE000"
MARKER_END = "\uE001"
GO_SERVER_URL = "http://localhost:8026/search"
# Definitions based on internal.rnc (excluding 'head')
BLOCK_TAGS = {"para", "verse", "quote", "dlist", "elist"}
# Structural parents allowed for a snippet root
VALID_PARENTS = {"div", "logical", "hand"}

class InternalWalker:

	def __init__(self, handler):
		# Initialize the walker with a target handler
		self.handler = handler

	def walk(self, root):
		# Initiate tree traversal
		self._walk_node(root)

	def _walk_node(self, node):
		# Process an individual node based on its type
		match node:
			case tree.String(): self.handler.on_text(node)
			case tree.Tag(): self._walk_tag(node)

	def _walk_tag(self, root):
		# Delegate tag processing based on structural function
		children = list(root)
		if root.name in ["logical", "title", "span", "search", "link", "identifier", "omission"]:
			for node in children: self._walk_node(node)
		elif root.name in ["translation", "bibliography"]:
			self._handle_section(root, children)
		elif root.name == "para": self._handle_para(children)
		elif root.name == "split": self._handle_split(root)
		elif root.name == "verse": self._handle_verse(root)
		elif root.name == "div": self._handle_div(root, children)
		elif root.name in ["elist", "dlist", "quote"]: self._handle_complex_blocks(root, children)
		elif root.name in ["npage", "nline", "ncell", "display", "note"]:
			self.handler.on_skipped_node(root)
		else:
			for node in children: self._walk_node(node)

	def _handle_section(self, root, children):
		# Process a section node while skipping its header element
		head = root.first("stuck-child::head")
		for node in children:
			if node is head: continue
			self._walk_node(node)

	def _handle_para(self, children):
		# Handle paragraph nodes appending virtual space
		for node in children: self._walk_node(node)
		self.handler.on_virtual("\n")

	def _handle_split(self, root):
		# Handle split nodes extracting searchable representation
		search_node = root.first("search")
		if search_node: self._walk_node(search_node)

	def _handle_div(self, root, children):
		# Skip phantom divisions or process standard divisions
		if common.to_boolean(root["phantom"]):
			self.handler.on_skipped_node(root)
			return
		head = root.first("stuck-child::head")
		for node in children:
			if node is head: continue
			self._walk_node(node)
		self.handler.on_virtual("\n")

	def _handle_complex_blocks(self, root, children):
		# Delegate processing for lists and quotes
		if root.name == "elist": self._handle_elist(root)
		elif root.name == "dlist": self._handle_dlist(root)
		elif root.name == "quote":
			source = root.first("stuck-child::source")
			self.handler.on_virtual("\t")
			for node in children:
				if node is source: continue
				self._walk_node(node)

	def _handle_verse(self, root):
		# Iterate through verse lines and append virtual space if broken
		first = True
		for line in root.find("verse-line"):
			if first: first = False
			elif common.to_boolean(line["break"]): self.handler.on_virtual(" ")
			for child in list(line): self._walk_node(child)

	def _handle_elist(self, root):
		# Process enumerated lists with generated labels
		labels = generate_list_labels(root)
		for label, item in zip(labels, root.find("item")):
			for c in label: self.handler.on_virtual(c)
			self.handler.on_virtual(" ")
			for thing in list(item): self._walk_node(thing)

	def _handle_dlist(self, root):
		# Process definition lists generating virtual arrows
		keys = root.find("key")
		values = root.find("value")
		for key, value in zip(keys, values):
			for thing in list(key): self._walk_node(thing)
			self.handler.on_virtual("➤")
			for thing in list(value): self._walk_node(thing)
			self.handler.on_virtual("\n")

def generate_list_labels(node):
	# Yield progressive labels based on list type
	match node["type"]:
		case "plain":
			while True: yield "◦"
		case "bulleted":
			while True: yield "•"
		case "numbered":
			i = 0
			while True:
				i += 1
				yield f"{i}."
		case _: raise Exception(f"bad value: {node!r}")

class TextExtractor:

	def __init__(self):
		# Initialize extraction buffer
		self.buf = []

	def on_text(self, node):
		# Append translated string to buffer
		self.buf.append(node.data)

	def on_virtual(self, char):
		# Append virtual structural character to buffer
		self.buf.append(char)

	def on_skipped_node(self, node):
		# Ignore explicitly skipped nodes
		pass

	def get_result(self):
		# Concatenate and return final extracted text
		return "".join(str(s) for s in self.buf).rstrip()

def extract_text(root: tree.Node):
	# Extract plain text representation from a DOM tree
	handler = TextExtractor()
	walker = InternalWalker(handler)
	walker.walk(root)
	return handler.get_result()

class Highlighter:

	def __init__(self, marked_stream, counter):
		# Initialize the highlighter with a shared counter for unique IDs
		self.hit_ranges = self._extract_ranges(marked_stream)
		self.cursor = 0
		self.counter = counter

	def highlight(self, root: tree.Node):
		# Traverse the DOM to apply match elements
		if not self.hit_ranges: return
		walker = InternalWalker(self)
		walker.walk(root)

	def on_text(self, node):
		# Evaluate and split text nodes intersecting with search hits
		text = node.data
		length = len(text)
		mask = self._compute_mask(length)
		self.cursor += length
		if any(mask): self._apply_mask(node, text, mask)

	def on_virtual(self, char):
		# Advance the virtual cursor for structural spacing
		self.cursor += len(char)

	def on_skipped_node(self, node):
		# Apply highlight to entire leaves if enclosed within a match boundary
		if node.name in {"npage", "nline", "ncell", "display"}: return
		if self._is_inside_match(): self._highlight_leaves(node)

	def _extract_ranges(self, stream):
		# Parse internal markers to compute intersection ranges
		ranges, stack, idx = [], [], 0
		for char in stream:
			if char == MARKER_START: stack.append(idx)
			elif char == MARKER_END:
				if stack: ranges.append((stack.pop(), idx))
			else: idx += 1
		return sorted(ranges)

	def _compute_mask(self, length):
		# Create a boolean mask indicating characters to highlight
		mask = [False] * length
		start, end = self.cursor, self.cursor + length
		for h_start, h_end in self.hit_ranges:
			i_start, i_end = max(start, h_start), min(end, h_end)
			if i_start < i_end:
				mask[i_start - start : i_end - start] = [True] * (i_end - i_start)
		return mask

	def _apply_mask(self, node, text, mask):
		# Segment text nodes and wrap highlighted portions
		nodes, buf = [], []
		highlighting = mask[0]
		for i, char in enumerate(text):
			if mask[i] != highlighting:
				self._flush(nodes, buf, highlighting)
				highlighting = mask[i]
			buf.append(char)
		self._flush(nodes, buf, highlighting)
		node.replace_with(*nodes)

	def _flush(self, nodes, buf, highlighting):
		# Consume the character buffer and generate an identified match node
		if not buf: return
		content = "".join(buf)
		buf.clear()
		if highlighting:
			self.counter[0] += 1
			match_node = tree.Tag("match")
			match_node["id"] = f"match-{self.counter[0]}"
			match_node.append(tree.String(content))
			nodes.append(match_node)
		else: nodes.append(tree.String(content))

	def _is_inside_match(self):
		# Check if the current cursor position falls strictly within a hit
		for start, end in self.hit_ranges:
			if start <= self.cursor < end: return True
		return False

	def _highlight_leaves(self, node):
		# Recursively tag terminal nodes while generating unique identifiers
		if isinstance(node, tree.String):
			self.counter[0] += 1
			match_node = tree.Tag("match")
			match_node["id"] = f"match-{self.counter[0]}"
			node.replace_with(match_node)
			match_node.append(node)
		elif isinstance(node, tree.Tag) and node.name != "search":
			for child in list(node): self._highlight_leaves(child)

class SnippetGenerator:

	def __init__(self, doc, context_chars=80):
		# Initialize the generator with the root document and context limit
		self.doc = doc
		self.context_chars = context_chars
		self.seen_blocks = set()

	def generate(self):
		# Tag ancestors and prune isolated blocks around matches
		roots = self._get_roots()
		if not roots: return
		for root in roots: self._mark_match_ancestors(root)
		blocks = []
		for root in roots: self._collect_blocks_from_root(root, blocks)
		for block in blocks:
			pruner = BlockPruner(block, self.context_chars)
			pruner.prune()

	def _mark_match_ancestors(self, node):
		# Recursively assign match attribute to all ancestors of a hit
		has_match = False
		if getattr(node, "name", None) == "match": has_match = True
		if isinstance(node, tree.Tag):
			for child in list(node):
				if self._mark_match_ancestors(child): has_match = True
			if has_match and node.name != "match":
				try: node["match"] = "true"
				except Exception: pass
		return has_match

	def _get_roots(self):
		# Identify the primary structural nodes for snippet extraction
		roots = []
		for path in ("/document/edition/logical", "/document/hand", "/document/summary"):
			node = self.doc.first(path)
			if node: roots.append(node)
		return roots

	def _collect_blocks_from_root(self, root, blocks):
		# Gather unique eligible block containers enclosing search hits
		matches = []
		self._collect_matches(root, matches)
		for m in matches:
			eligible = self._find_eligible_block(m)
			if eligible and id(eligible) not in self.seen_blocks:
				self.seen_blocks.add(id(eligible))
				blocks.append(eligible)

	def _collect_matches(self, n, matches_list):
		# Traverse the tree to compile a list of all match nodes
		if isinstance(n, tree.Tag):
			if n.name == "match": matches_list.append(n)
			for child in list(n): self._collect_matches(child, matches_list)

	def _find_eligible_block(self, node):
		# Ascend the DOM to find the nearest valid block container
		curr = node
		while isinstance(curr, tree.Tag):
			if curr.name in BLOCK_TAGS:
				parent = curr.parent
				assert parent is not None
				if isinstance(parent, tree.Tag) and parent.name in VALID_PARENTS: return curr
			curr = curr.parent
		return None

class BlockPruner:

	def __init__(self, block, context_chars):
		# Initialize pruner with target block and context limits
		self.block = block
		self.context_chars = context_chars
		self.events = []
		self.char_keep = []
		self.inline_tags = {
			"span", "link", "note", "npage", "nline", "ncell",
			"display", "split", "search", "name", "identifier", "match"
		}
		self.immune_tags = {"head", "source"}
		self.milestone_tags = {"npage", "nline", "ncell"}
		self.distance_tags = {"verse-line", "item"}
		self.strict_tags = {"key", "value"}
		self.snippet_items = self.distance_tags | self.strict_tags | BLOCK_TAGS

	def prune(self):
		# Bypass pruning entirely if context limit is negative
		if self.context_chars < 0: return
		for child in list(self.block):
			self._linearize(child, False, False, False, None)
		self._compute_mask()
		if not self.char_keep or all(self.char_keep): return
		self.block.clear()
		self._rebuild_tree()

	def _has_match_attr(self, node):
		# Check if a node possesses the global match attribute
		try: return node["match"] == "true"
		except Exception: return False

	def _linearize(self, node, in_match, in_ms, in_im, cur_si):
		# Flatten tree into events tracking grapheme clusters
		if isinstance(node, tree.String):
			text = str(node)
			bi = icu.BreakIterator.createCharacterInstance(icu.Locale.getRoot())
			bi.setText(text)
			start = bi.first()
			for end in bi:
				self.events.append(("char", text[start:end], in_match, in_ms, in_im, cur_si))
				start = end
		elif isinstance(node, tree.Tag):
			m = in_match or node.name == "match"
			ms = in_ms or node.name in self.milestone_tags
			im = in_im or node.name in self.immune_tags
			si = node if node.name in self.snippet_items else cur_si
			self.events.append(("open", node))
			for child in list(node):
				self._linearize(child, m, ms, im, si)
			self.events.append(("close", node.name))

	def _compute_mask(self):
		# Determine which grapheme clusters fall within the window
		char_idx = [i for i, ev in enumerate(self.events) if ev[0] == "char"]
		n = len(char_idx)
		if n == 0: return
		dist = self._compute_distances(char_idx, n)
		keep = [d <= self.context_chars or self.events[char_idx[i]][4] for i, d in enumerate(dist)]
		self._snap_to_word_boundaries(keep, char_idx, n)
		self._trim_mask(keep, char_idx, n)
		self._clean_empty_omissions(keep, char_idx, n)
		self._apply_snippet_item_rules(keep, char_idx, n)
		self.char_keep = keep

	def _clean_empty_omissions(self, keep, char_idx, n):
		# Revert omissions that contain no substantive text
		boundaries = {' ', '-', '\t', '\n', '\r'}
		i = 0
		while i < n:
			if not keep[i]:
				start = i
				while i < n and not keep[i]: i += 1
				end = i - 1
				has_real = False
				for k in range(start, end + 1):
					ev = self.events[char_idx[k]]
					if not ev[3] and not ev[4] and ev[1] not in boundaries:
						has_real = True
						break
				if not has_real:
					for k in range(start, end + 1): keep[k] = True
			else: i += 1

	def _snap_to_word_boundaries(self, keep, char_idx, n):
		# Adjust cut-off points to respect word integrity
		i = 0
		while i < n:
			if keep[i]:
				start = i
				while i < n and keep[i]: i += 1
				end = i - 1
				ms, me = self._find_matches_in_segment(char_idx, start, end)
				if ms <= end:
					self._snap_left_edge(keep, char_idx, start, ms)
					self._snap_right_edge(keep, char_idx, end, me)
			else: i += 1

	def _find_matches_in_segment(self, char_idx, start, end):
		# Locate the first and last match clusters within a kept segment
		ms = start
		while ms <= end and not self.events[char_idx[ms]][2]: ms += 1
		me = end
		while me >= start and not self.events[char_idx[me]][2]: me -= 1
		return ms, me

	def _snap_left_edge(self, keep, char_idx, start, ms):
		# Retract the left edge to the nearest boundary if context remains
		boundaries = {' ', '-', '\t', '\n', '\r'}
		if start >= ms: return
		B = start
		while B < ms and self.events[char_idx[B]][1] not in boundaries: B += 1
		if B < ms and self._has_normal_chars(char_idx, B + 1, ms, boundaries):
			for k in range(start, B): keep[k] = False

	def _snap_right_edge(self, keep, char_idx, end, me):
		# Retract the right edge to the nearest boundary if context remains
		boundaries = {' ', '-', '\t', '\n', '\r'}
		if end <= me: return
		B = end
		while B > me and self.events[char_idx[B]][1] not in boundaries: B -= 1
		if B > me and self._has_normal_chars(char_idx, me + 1, B, boundaries):
			for k in range(B + 1, end + 1): keep[k] = False

	def _has_normal_chars(self, char_idx, start_idx, end_idx, boundaries):
		# Verify the presence of text content between boundaries
		for k in range(start_idx, end_idx):
			if self.events[char_idx[k]][1] not in boundaries: return True
		return False

	def _compute_distances(self, char_idx, n):
		# Calculate distance ignoring boundaries and special elements
		cost_free = {' ', '-', '\t', '\n', '\r'}
		dist = [float('inf')] * n
		self._sweep_distances(char_idx, dist, cost_free, range(n))
		self._sweep_distances(char_idx, dist, cost_free, range(n - 1, -1, -1))
		return dist

	def _sweep_distances(self, char_idx, dist, cost_free, indices):
		# Perform a directional sweep to measure proximity to matches
		cur_dist = float('inf')
		for i in indices:
			ev = self.events[char_idx[i]]
			if ev[2]: cur_dist = 0
			elif not ev[3] and not ev[4] and ev[1] not in cost_free:
				if cur_dist != float('inf'): cur_dist += 1
			dist[i] = min(dist[i], cur_dist)

	def _trim_mask(self, keep, char_idx, n):
		# Remove isolated milestone characters at the edges
		i = 0
		while i < n:
			if keep[i]:
				start = i
				while i < n and keep[i]: i += 1
				end = i - 1
				if start > 0:
					while start <= end and keep[start] and self.events[char_idx[start]][3]:
						keep[start] = False
						start += 1
				if end < n - 1:
					while end >= start and keep[end] and self.events[char_idx[end]][3]:
						keep[end] = False
						end -= 1
			else: i += 1

	def _apply_snippet_item_rules(self, keep, char_idx, n):
		# Prevent omissions in items lacking the match ancestor attribute
		active_ids = set()
		for i in range(n):
			si = self.events[char_idx[i]][5]
			if si is not None and self._has_match_attr(si):
				active_ids.add(id(si))
		for i in range(n):
			si = self.events[char_idx[i]][5]
			if si is not None and id(si) not in active_ids:
				keep[i] = True

	def _rebuild_tree(self):
		# Reconstruct the DOM tree applying omissions
		self.tag_stack, self.dom_stack = [], [self.block]
		self.is_omitting, self.char_buffer = False, []
		self.char_cursor = 0
		for ev in self.events:
			if ev[0] == "char":
				self._handle_char(ev[1], self.char_keep[self.char_cursor])
				self.char_cursor += 1
			elif ev[0] == "open": self._handle_open(ev[1])
			elif ev[0] == "close": self._handle_close()
		self._flush_buffer()

	def _handle_char(self, char, keep):
		# Trigger state changes upon encountering boundaries
		omitting = not keep
		if omitting != self.is_omitting: self._switch_state(omitting)
		self.char_buffer.append(char)

	def _handle_open(self, node):
		# Apply state before opening a new tag
		self._flush_buffer()
		if node.name not in self.inline_tags and self.is_omitting:
			self._switch_state(False)
		elif node.name in self.inline_tags and self.char_cursor < len(self.char_keep):
			omitting = not self.char_keep[self.char_cursor]
			if omitting != self.is_omitting: self._switch_state(omitting)
		self.tag_stack.append(node)
		new_node = self._clone_tag(node)
		self.dom_stack[-1].append(new_node)
		self.dom_stack.append(new_node)

	def _handle_close(self):
		# Close the current tag and force boundaries on blocks
		self._flush_buffer()
		tag = self.tag_stack[-1]
		if tag.name not in self.inline_tags and self.is_omitting:
			self._switch_state(False)
		self.tag_stack.pop()
		self.dom_stack.pop()

	def _switch_state(self, omitting):
		# Reorganize only inline open tags across the omission boundary
		self._flush_buffer()
		inline_count = 0
		for tag in reversed(self.tag_stack):
			if tag.name in self.inline_tags: inline_count += 1
			else: break
		for _ in range(inline_count): self.dom_stack.pop()
		self.is_omitting = omitting
		if omitting:
			om_node = tree.Tag("omission")
			self.dom_stack[-1].append(om_node)
			self.dom_stack.append(om_node)
		else: self.dom_stack.pop()
		for orig_node in self.tag_stack[len(self.tag_stack)-inline_count:]:
			new_node = self._clone_tag(orig_node)
			self.dom_stack[-1].append(new_node)
			self.dom_stack.append(new_node)

	def _flush_buffer(self):
		# Append accumulated characters to the active node
		if not self.char_buffer: return
		text = "".join(self.char_buffer)
		self.dom_stack[-1].append(tree.String(text))
		self.char_buffer.clear()

	def _clone_tag(self, original):
		# Create an empty duplicate of a tag
		clone = tree.Tag(original.name)
		try:
			for k, v in original.items(): clone[k] = v
		except Exception: pass
		return clone

class FieldTruncater:

	def __init__(self, max_chars=300):
		# Initialize truncater with maximum character count and standard block definitions
		self.max_chars = max_chars
		self.events = []

	def truncate(self, node):
		# Main entry point to isolate the first block and truncate its text if necessary
		if not node: return
		removed_blocks = self._isolate_first_block(node)
		self.events = []
		self._linearize(node)
		total_chars = self._count_chars()
		cutoff = total_chars
		if total_chars > self.max_chars:
			cutoff = self._find_cutoff_index()
		if cutoff < total_chars or removed_blocks:
			node.clear()
			self._rebuild_tree(node, cutoff)

	def _isolate_first_block(self, node):
		# Retain only the first block element and discard all subsequent siblings
		children_to_keep = []
		original_count = len(list(node))
		for child in list(node):
			children_to_keep.append(child)
			if getattr(child, "name", None) in BLOCK_TAGS: break
		removed = len(children_to_keep) < original_count
		if removed:
			node.clear()
			for c in children_to_keep: node.append(c)
		return removed

	def _linearize(self, node):
		# Flatten the DOM tree into events while explicitly ignoring search nodes
		if getattr(node, "name", None) == "search": return
		if isinstance(node, tree.String):
			for char in node.data: self.events.append(("char", char))
		elif isinstance(node, tree.Tag):
			self.events.append(("open", node))
			for child in list(node): self._linearize(child)
			self.events.append(("close", node.name))

	def _count_chars(self):
		# Return the total number of character events
		return sum(1 for e in self.events if e[0] == "char")

	def _find_cutoff_index(self):
		# Build plain text to find sentence boundaries within the character limit
		char_events = [e[1] for e in self.events if e[0] == "char"]
		full_text = "".join(char_events)
		if len(full_text) <= self.max_chars: return len(full_text)
		return self._find_sentence_cutoff(full_text)

	def _find_sentence_cutoff(self, text):
		# Helper to find cutoff by sentences to respect the character constraint
		sentences = re.split(r'(?<=[.!?])\s+', text)
		current_text = ""
		for s in sentences:
			if not current_text: current_text = s
			elif len(current_text) + 1 + len(s) <= self.max_chars:
				current_text += " " + s
			else: break
		return len(current_text)

	def _rebuild_tree(self, root, cutoff):
		# Reconstruct the tree up to the cutoff index and append an omission marker
		dom_stack = [root]
		char_count = 0
		added_omission = False
		for ev in self.events:
			res = self._process_rebuild_event(ev, root, dom_stack, cutoff, char_count)
			char_count, added_omission = res[0], res[1] or added_omission
		if not added_omission: self._add_omission(dom_stack[-1])

	def _process_rebuild_event(self, ev, root, dom_stack, cutoff, char_count):
		# Process a single event during tree reconstruction
		added = False
		if ev[0] == "open" and ev[1] is not root:
			clone = tree.Tag(ev[1].name)
			for k, v in ev[1].items(): clone[k] = v
			dom_stack[-1].append(clone)
			dom_stack.append(clone)
		elif ev[0] == "char":
			if char_count < cutoff: dom_stack[-1].append(tree.String(ev[1]))
			char_count += 1
			if char_count == cutoff:
				self._add_omission(dom_stack[-1])
				added = True
		elif ev[0] == "close" and ev[1] != root.name: dom_stack.pop()
		return char_count, added

	def _add_omission(self, parent_node):
		# Append a space text node before the omission tag to ensure correct typography
		parent_node.append(tree.String(" "))
		om = tree.Tag("omission")
		om.append(tree.String("[\N{horizontal ellipsis}]"))
		parent_node.append(om)

def extract_one_text(xpath):
	# Extract a single text representation using xpath
	def extractor(doc):
		node = doc.first(xpath)
		return extract_text(node) if node else ""
	return extractor

def extract_list_text(xpath):
	# Extract a list of text representations using xpath
	def extractor(doc):
		return [extract_text(n) for n in doc.find(xpath)]
	return extractor

def _get_direct_children(node, tag_name):
	# Return a list of direct children matching the tag name to prevent deep traversal
	return [c for c in list(node) if getattr(c, "name", None) == tag_name]

def get_flat_people(xpath):
	# Extract a flat list of identifiers and names for people or linear data
	def extractor(doc):
		res = []
		for node in doc.find(xpath):
			id_nodes = _get_direct_children(node, "identifier")
			res.append(extract_text(id_nodes[0]) if id_nodes else "")
			name_nodes = _get_direct_children(node, "name")
			res.append(extract_text(name_nodes[0]) if name_nodes else "")
		return res
	return extractor

SEARCH_CONFIG = {
	"ident": {
		"extractor": extract_one_text("/document/identifier"),
		"type": "string",
		"highlight": "/document/identifier"
	},
	"logical": {
		"extractor": extract_one_text("/document/edition/logical"),
		"type": "string",
		"highlight": "/document/edition/logical"
	},
	"translation": {
		"extractor": extract_one_text("/document/translation"),
		"type": "string",
		"highlight": "/document/edition/translation"
	},
	"bibliography": {
		"extractor": extract_one_text("/document/bibliography"),
		"type": "string",
		"highlight": "/document/edition/bibliography"
	},
	"title": {
		"extractor": extract_list_text("/document/title"),
		"type": "list",
		"highlight": "/document/title"
	},
	"summary": {
		"extractor": extract_one_text("/document/summary"),
		"type": "string",
		"highlight": "/document/summary"
	},
	"repo_id": {
		"extractor": extract_one_text("/document/repository/identifier"),
		"type": "string",
		"highlight": "/document/repository/identifier"
	},
	"repo_name": {
		"extractor": extract_one_text("/document/repository/name"),
		"type": "string",
		"highlight": "/document/repository/name"
	},
	"hand": {
		"extractor": extract_one_text("/document/hand"),
		"type": "string",
		"highlight": "/document/hand"
	},
	"author": {
		"extractor": get_flat_people("/document/author"),
		"type": "people",
		"highlight": "/document/author"
	},
	"editor": {
		"extractor": get_flat_people("/document/editor"),
		"type": "people",
		"highlight": "/document/editor"
	},
	"lang": {
		"extractor": get_flat_people("/document/languages/language"),
		"type": "people",
		"highlight": "/document/languages/language"
	},
	"script": {
		"extractor": get_flat_people("/document/scripts/script"),
		"type": "people",
		"highlight": "/document/scripts/script"
	}
}

def query_search_service(query_str, offset=0, limit=20, sort="title"):
	# Query the backend search service and process occurrences
	norm_query = unicodedata.normalize('NFC', query_str)
	ast = query.parse_query(norm_query)
	q_json = common.to_json(ast.serialize())
	params = {"q": q_json, "offset": offset, "limit": limit, "sort": sort}
	resp = requests.get(GO_SERVER_URL, params=params)
	resp.raise_for_status()
	data = resp.json()
	processed_matches = process_matches(data.get("matches", []))
	return {
		"query": query_str,
		"match_count": data.get("count", 0),
		"matches": processed_matches,
		"sort": data.get("sort", sort)
	}

def query_match_document(ident, query_str="") \
	-> tuple[None, None] | tuple[tree.Tree, tree.Tree]:
	# Retrieve and highlight a full document without applying snippet pruning
	q_json = ""
	if query_str:
		norm_query = unicodedata.normalize('NFC', query_str)
		ast = query.parse_query(norm_query)
		q_json = common.to_json(ast.serialize())
	params = {"ident": ident, "q": q_json}
	url = GO_SERVER_URL.replace("/search", "/match")
	resp = requests.get(url, params=params)
	resp.raise_for_status()
	data = resp.json()
	matches = data.get("matches", [])
	assert len(matches) <= 1
	if not matches:
		return None, None
	item = matches[0]
	xml_str = item["source"]
	doc = tree.parse_string(xml_str)
	if query_str:
		highlight_document(doc, item)
	original = tree.parse_string(item["original"])
	return doc, original

def process_matches(raw_matches):
	# Transform raw matches into highlighted document trees
	results = []
	for item in raw_matches:
		processed = process_single_match(item)
		if processed: results.append(processed)
	return results

def process_single_match(item):
	# Parse XML source and apply structural pruning
	xml_str = item.get("source", "")
	if not xml_str: return None
	try:
		doc = tree.parse_string(xml_str)
		highlight_document(doc, item)
		SnippetGenerator(doc).generate()
		truncater = FieldTruncater(max_chars=300)
		for path in ["/document/summary", "/document/hand"]:
			node = doc.first(path)
			if node: truncater.truncate(node)
		return doc
	except Exception as e:
		import traceback
		print(traceback.format_exc())
		print(f"Error processing match {item.get('ident')}: {e}")
		return None

def highlight_document(doc, item_data):
	# Traverse configured fields and apply coordinated highlighting
	counter = [0]
	for field, config in SEARCH_CONFIG.items():
		xpath = config.get("highlight")
		if not xpath: continue
		marked_data = item_data.get(field)
		if not marked_data: continue
		nodes = list(doc.find(xpath))
		if nodes:
			_dispatch_highlight(nodes, marked_data, config, counter)
		if field == "script":
			_highlight_language_scripts(doc, marked_data, counter)

def _highlight_language_scripts(doc, marked_data, counter):
	# Traverse script nodes and apply highlights exactly as returned by the search engine.
	lang_scripts = list(doc.find("/document/languages/language/script"))
	if not lang_scripts or not marked_data: return
	id_map = {}
	for i in range(0, len(marked_data), 2):
		marked_id = marked_data[i]
		clean_id = marked_id.replace(MARKER_START, "").replace(MARKER_END, "").strip()
		marked_name = marked_data[i+1] if i + 1 < len(marked_data) else ""
		if clean_id:
			id_map[clean_id] = (marked_id, marked_name)
	for node in lang_scripts:
		id_nodes = _get_direct_children(node, "identifier")
		if not id_nodes: continue
		clean_id = extract_text(id_nodes[0]).strip()
		if clean_id in id_map:
			marked_id, marked_name = id_map[clean_id]
			if MARKER_START in marked_id:
				apply_string_highlight(id_nodes, marked_id, counter)
			name_nodes = _get_direct_children(node, "name")
			if name_nodes and MARKER_START in marked_name:
				apply_string_highlight(name_nodes, marked_name, counter)

def _dispatch_highlight(nodes, marked_data, config, counter):
	# Route the highlighting procedure according to field topography
	if config["type"] == "list" and isinstance(marked_data, list):
		apply_list_highlight(nodes, marked_data, counter)
	elif config["type"] == "people" and isinstance(marked_data, list):
		apply_people_highlight(nodes, marked_data, counter)
	else:
		apply_string_highlight(nodes, marked_data, counter)

def apply_list_highlight(nodes, marked_list, counter):
	# Map search hits across sequential lists
	for i, content in enumerate(marked_list):
		if MARKER_START in content and i < len(nodes):
			hl = Highlighter(content, counter)
			hl.highlight(nodes[i])

def apply_people_highlight(nodes, flat_list, counter):
	# Distribute highlighted markers across structured names and identifiers
	for i, node in enumerate(nodes):
		id_idx = 2 * i
		name_idx = 2 * i + 1
		if id_idx < len(flat_list):
			targets = _get_direct_children(node, "identifier")
			if targets: apply_string_highlight(targets, flat_list[id_idx], counter)
		if name_idx < len(flat_list):
			targets = _get_direct_children(node, "name")
			if targets: apply_string_highlight(targets, flat_list[name_idx], counter)

def apply_string_highlight(nodes, marked_string, counter):
	# Instantiate highlighting for solitary character sequences
	if MARKER_START in marked_string:
		hl = Highlighter(marked_string, counter)
		hl.highlight(nodes[0])

def prepare_search_data(doc):
	# Compile normalized structural fields for database insertion
	data = {}
	for field, config in SEARCH_CONFIG.items():
		extractor = config["extractor"]
		data[field] = extractor(doc)
	data["source"] = doc.xml(add_xml_prefix=False)
	return data

def eprint(*args, **kwargs):
	# Print output directly to the standard error stream
	kwargs.setdefault("file", sys.stderr)
	print(*args, **kwargs)

def cli_search(query):
	# Execute a command line search and display initial snippet
	import snip
	r = query_search_service(query, offset=0, limit=20, sort="title")
	if r["match_count"] < 1:
		eprint("no match")
		return
	t = r["matches"][0]
	print(t.first("//logical").xml())
	doc = snip.process(t)

@common.transaction("texts")
def main():
	import ingest, enrich
	doc = tree.parse_string(sys.stdin.read())
	doc = ingest.process_tree(doc)
	enrich.process(doc)
	translation = doc.first("/document/bibliography")
	assert translation
	print(extract_text(translation))

if __name__ == "__main__":
	main()
