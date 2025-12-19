"""XML tree representation.

Node types are: `Tree`, `Tag`, `Comment`, `String`, `Instruction`. Attributes
are not represented as nodes, even though they are treated like that in the
xpath model, because this would be weird in python.

All node types derive from an abstract base class `Node`. `Tree` and `Tag` nodes
derive from an abstract class `Branch`, which itself derives from `Node`. There
is no inheritance relationship between concrete node types. For instance,
`Comment` is not a subclass of `String`, unlike in BeautifulSoup. Thus, to check
whether a node is of a concrete given type `T`, using `isinstance(node, T)`,
etc. is sufficient. And to check whether a node is a branch or a leaf, it is
sufficient to check `isinstance(node, Branch)`.

When parsing documents and when modifying attributes, we always normalize spaces
in attributes: we replace all sequences of whitespace characters with " " and we
trim whitespace from both sides. Thus, an attribute with only whitespace is
considered empty. Furthermore, we don't make a distinction between an empty or
blank attribute and an attribute that is not explicitly given. Thus, we assume
that `<foo bar="">` and `<foo bar="  ">` are identical to `<foo>`. This is
wrong, but it doesn't cause much harm in practice, and considerably simplifies
processing. It is still possible to check whether an attribute is explicitly
given by using the Node.keys() method.

For simplicity, we do not deal with XML namespaces at all. We just remove
namespace prefixes in both elements and attributes. Thus, `<xsl:template>`
becomes `<template>`, and `<foo xml:lang="eng">` becomes `<foo lang="eng">`.
This means that we cannot deal with documents where namespaces are significant.
This also means that we cannot properly serialize XML documents that used
namespaces initially. However, the resulting simplicity trumps this
not-so-accurate processing.

We use XPath expressions for searching and matching, but only support a small
subset of it. Most notably, it is only possible to select `Tag` and `Tree`
nodes. Other types of nodes, attributes in particular, can only be used in
predicates viz. within brackets, as in `foo[@bar]`. We also do not support
expressions that index node sets in some way (because we are using generators
instead of lists for computing intermediate results). Thus, testing a node
position in a node set or evaluating the length of a node set is not possible.

There is one notable difference with XPath: the text() function does not return
strings from the tree, but returns instead a (space-normalized) string which
concatenates all string nodes under a given subtree.

For convenience, we add a few extra axes to XPath's default. They are:

* `stuck-child`.
        Returns the first child element of the current node, iff there is no
        text or just whitespace between the current node and this child. This
        only ever returns one child.
* `stuck-parent`.
        Reverse of stuck-child.
* `stuck-following-sibling`.
        Returns the first following sibling of the current node, iff there is no
        text or just whitespace between the current node and this sibling. This
        only ever returns one sibling.
* `stuck-preceding-sibling`.
        Reverse of stuck-preceding-sibling.

XPath expressions can use the following functions:

`glob(pattern[, text])`, `iglob(pattern[, text])`

Checks if `text` matches the given glob `pattern`. If `text` is not given, it
defaults to the node's text contents. `iglob` is like `glob`, but is
case-insensitive. In addition, we have:

`regex(pattern[, text])`

Like `glob`, but for regular expressions. Matching is unanchored, so `^` and `$`
must be used if the idea is to match a full string.

`name()` `mixed()`, `empty()`, `plain()`, `text()`

Returns the corresponding attributes in `Node`.

To evaluate an expression, we first convert it to straightforward python source
code, then compile the result, and finally run the code. Compiled expressions
are saved in a global table and are systematically reused. There is no caching
policy for now, so it is not a good idea to generate expressions on-the-fly.

The xpath.py command-line tool can be used for evaluating xpath expressions. If
it is not given any file to search into, it just prints the Python code that
will be used for evaluating the given expression.
"""

# TODO add a "fallback" handler (or maybe a different parser) for processing
# stuff simple document that are not necessarily XML viz. documents with
# several root elements or without a root element.

import os, re, io, collections, sys, fnmatch, tokenize, traceback
from xml.parsers import expat
from xml.sax.saxutils import escape as quote_string
from pegen.tokenizer import Tokenizer
from typing import SupportsIndex
from dharma.xpath_parser import Path, Step, Op, Func, GeneratedParser
from dharma import texts

Location = collections.namedtuple("Location", "start end line column")
"""Represents the location of a node in an XML file. Fields are:

* `start`: byte index of the start of the node
* `end`: idem for the end of the node
* `line`: line number (one-based)
* `column`: column number (one-based)
"""

# We don't use xml.sax.saxutils.quoteattr because it tries to use ' for
# quoting attributes, and people generally use " instead. We want to preserve
# the original as much as possible.
attribute_tbl = str.maketrans({
	'"': "&quot;",
	"<": "&lt;",
	">": "&gt;",
	"&": "&amp;",
})

def escape_attribute(s):
	return s.translate(attribute_tbl)

def quote_attribute(s):
	return f'"{escape_attribute(s)}"'

def _sorted(nodes):
	"Sort nodes in document order. Returns a list."
	nodes = list(nodes)
	if not nodes:
		return nodes
	node_set = set(nodes)
	t = nodes[0].tree
	nodes.clear()
	def inner(root):
		if root in node_set:
			nodes.append(root)
		if isinstance(root, Branch):
			for child in root:
				inner(child)
	inner(t)
	assert len(nodes) == len(node_set)
	return nodes

def parse_string(source, path=None):
	"""Parse an XML string into a `Tree`. If `path` is given, it will be
	used as filename in error messages, and will be accessible through
	the `file` attribute."""
	#  We always pass byte strings to the parser because expat only
	# reports byte offsets, not code points offsets, so, to report
	# errors locations properly, we need a byte string.
	if isinstance(source, str):
		source = source.encode()
	try:
		return _Parser(source, path=path).parse()
	except expat.ExpatError as e:
		err = e
	# https://docs.python.org/3/library/pyexpat.html#xml.parsers.expat.XMLParserType
	# err.offset counts columns from 0
	raise Error(path=path or "",
		line=err.lineno, column=err.offset + 1,
		text=expat.errors.messages[err.code], source=source)

def parse(file, path=None):
	"""Parse an XML file into a `Tree`. The `file` argument can either be a
	file-like object or a string that indicates the file's path. The `path`
	argument can be used to indicate the file's path, for errors messages.
	If it is not given, the path of the file will be deduced from `file`,
	if possible."""
	if isinstance(file, texts.File):
		source = file.data
		if not path:
			path = file.full_path
	elif hasattr(file, "read"):
		# assume file-like
		source = file.read()
		if not path and file is not sys.stdin and hasattr(file, "name"):
			path = os.path.abspath(str(file.name))
	else:
		with open(file, "rb") as f:
			source = f.read()
		if not path:
			path = os.path.abspath(file)
	return parse_string(source, path=path)

class Node:

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.location: Location | None = None
		"""`Location` object, which indicates the boundaries of the
		subtree in the XML source it was constructed from. If the
	        subtree does not come from an XML file, `Location` is `None`.
	        Likewise, if the subtree is modified in some way, or if it is
	        extracted from the original tree or copied from it, `Location`
	        will be set to `None`."""
		# Parent node.
		self._parent = None
		self.notes: dict = {}
		"""A dictionary for storing arbitrary data."""

	@property
	def tree(self):
		"""The `Tree` this node belongs to. If the node is a `Tree`,
		this returns the `Tree` itself."""
		node = self
		while not isinstance(node, Tree):
			node = node.parent
		return node

	@property
	def file(self) -> str | None:
		"Path of the XML file this subtree was constructed from."
		return self.tree.file

	@property
	def parent(self) -> "Branch | None":
		"""Parent node. All nodes have a parent, except `Tree` nodes,
		whose parent is `None`."""
		# Newly created nodes are not immediately attached to a tree.
		# It is only if an attempt is made to access a node's tree
		# that a new tree is allocated. We do this to avoid creating
		# new tree objects for each new node, when in practice most
		# nodes will be immediately appended to an existing tree.
		ret = self._parent
		if ret is None:
			ret = Tree()
			self._parent = ret
			list.append(ret, self)
		return ret

	@property
	def path(self) -> str:
		"The path of this node. See the `locate` method."
		raise NotImplementedError

	@property
	def mixed(self) -> bool:
		"""Whether this node has both `Tag` and non-blank `String`
		children. This can only be called on `Branch` nodes."""
		raise Exception("invalid operation")

	@property
	def empty(self) -> bool:
		"""`True` if this node has no `Tag` children nor non-blank
		`String` children. This can only be called on `Branch` nodes."""
		raise Exception("invalid operation")

	@property
	def plain(self) -> bool:
		"""`True` if this node is a `String`, or if it is a `Branch`
		that has no children or only `String` children (discounting
		comments and processing instructions)."""
		return False

	def __hash__(self):
		return id(self)

	def __bool__(self):
		return True

	@property
	def source(self) -> str | None:
		"""XML source of this subtree, as it appears in the file it
		was parsed from, as a string. If the `location` member is
		`None`, `source` will also be `None`.
		"""
		source = self.byte_source
		if source:
			return source.decode()

	@property
	def byte_source(self) -> bytes | None:
		"XML source of this subtree, in bytes, encoded as UTF-8."
		source = self.tree.byte_source
		location = self.location
		if source and location:
			return source[location.start:location.end]

	@property
	def root(self) -> "Tag":
		"""The root `Tag` node of the `Tree` this subtree belongs to.
		Raises an error if the `Tree` does not have one or has many.
		"""
		return self.tree.root

	def append(self, node: "Node | str"):
		raise NotImplementedError

	def prepend(self, node: "Node | str"):
		raise NotImplementedError

	def stuck_child(self):
		"""Returns the first `Tag` child of this node, if it has one
		and if there is no intervening non-blank text in-between. Can
		only be called on `Branch` nodes.
		"""
		pass

	def stuck_parent(self):
		"Reverse of `stuck_child()`."
		parent = self.parent
		if parent and parent.stuck_child() is self:
			return parent

	def stuck_following_sibling(self):
		"""Returns the first `Tag` sibling of this node, if it has one
		and if there is no intervening non-blank text in-between. Can
		only be called on `Tag` nodes.
		"""
		raise Exception("bad operation")

	def stuck_preceding_sibling(self):
		"""Reverse of stuck_preceding_sibling()."""
		raise Exception("bad operation")

	def strings(self) -> list["String"]:
		return []

	def delete(self):
		"""Removes this node and all its descendants from the tree.
		Returns the removed subtree."""
		parent = self._parent
		if parent:
			parent.remove(self)
			return self
		self._parent = None
		self.location = None
		return self

	_location_re = re.compile(r"/(\w+)\[([1-9][0-9]*)\]", re.ASCII)

	def locate(self, path):
		"""Finds the node that matches the given xpath expression.
		This only works for basic expressions of the form:
		`/`, `/foo[1]`, `/foo[1]/bar[5]`, etc. The path of a node
		is given in its `path` attribute.
		"""
		orig = path
		node = self.tree
		if path == "/":
			return node
		while True:
			match = self._location_re.match(path)
			if not match:
				raise Exception(f"invalid location {orig!r}")
			name, index = match.group(1), int(match.group(2))
			i = 0
			for node in node:
				if isinstance(node, Tag) and node.name == name:
					i += 1
					if i == index:
						break
			else:
				raise Exception(f"node {orig!r} not found")
			end = match.end()
			if end == len(path):
				break
			path = path[end:]
		return node

	def find(self, path: str, sort: bool=False) -> list['Node']:
		"""Finds nodes that match the given XPath expression.

		Returns a list of matching nodes. If `sort` is True, nodes are
		sorted in document order before being returned. Otherwise, they
		might appear in any order.
		"""
		f = generator.compile(path)
		if sort:
			return _sorted(f(self))
		return list(f(self))

	def first(self, path: str, sort: bool=False) -> "Node | None":
		"""Like the `find` method, but returns only the first matching
		node, or `None` if there is no match."""
		f = generator.compile(path)
		if sort:
			return next(_sorted(f(self)), None)
		return next(f(self), None)

	@staticmethod
	def match_func(path: str):
		"""Returns a function that matches the given path if called on
		a `Node` object. See the documentation of `Node.matches()`."""
		return generator.compile(path, search=False)

	def matches(self, path: str) -> bool:
		"""Checks if this node matches the given XPath expression.
		Returns a boolean.

		The expression is evaluated like an XSLT pattern. For details,
		see the XSLT 1.0 standard, under § 5.2 Patterns.
		"""
		f = self.match_func(path)
		return f(self)

	def children(self) -> list['Node']:
		"""Returns a list of `Tag` children of this node."""
		return []

	def replace_with(self, other) -> 'Node':
		"""Removes this node and its descendants from the tree, and
		puts another node in its place. Returns the removed subtree.
		"""
		parent = self.parent
		assert parent is not None
		i = parent.index(self)
		del parent[i]
		parent.insert(i, other)
		return self

	def insert_after(self, other):
		"""Insert a node just after the current one.

		This cannot be called on a `Tree`, obviously."""
		parent = self.parent
		assert parent is not None
		i = parent.index(self)
		parent.insert(i + 1, other)

	def insert_before(self, other: "Node | str"):
		"""Insert a node just before the current one.

		This cannot be called on a `Tree`, obviously."""
		parent = self.parent
		assert parent is not None
		i = parent.index(self)
		parent.insert(i, other)

	def comment_out(self, **kwargs):
		"""Comment out a node viz. replace it with a commented out XML
		representation of it. Keyword arguments are the same as the ones
		of the `.xml()` method."""
		tmp = self.xml(**kwargs)
		self.replace_with(Comment(tmp))
		return self

	def text(self, space="default") -> str:
		"""Returns the text contents of this subtree. Per default, we do
		normalize-space(); to prevent this, pass `space="preserve"`.
		"""
		return ""

	def xml(self, strip_comments=False, strip_instructions=False,
		html=False, color=False, add_xml_prefix=True):
		"""Returns an XML representation of this subtree.

		If `html` is true, the result will be escaped, for inclusion
		in an HTML file. If `color` is true, the result will be
		colorized, either through CSS classes (if `html` is true),
		or with ANSI escapes codes (otherwise).
		"""
		fmt = Formatter(strip_comments=strip_comments,
			strip_instructions=strip_instructions, html=html,
			color=color, add_xml_prefix=add_xml_prefix)
		fmt.format(self)
		return fmt.text()

	def html(self):
		fmt = Formatter(strip_comments=True, strip_instructions=True,
			html=False, color=False, add_xml_prefix=False, self_closing=False)
		fmt.format(self)
		return fmt.text()

	def __iter__(self):
		raise NotImplementedError

	def __copy__(self):
		return self.copy()

	def __deepcopy__(self, memo):
		return self.copy()

	def copy(self):
		"""Makes a copy of this subtree. The returned object holds no
		reference to the original. It is bound to a new `Tree`."""
		raise NotImplementedError

	def unwrap(self):
		"""Removes a node from the tree but leaves its descendants
		in-place. Returns the detached node.

		This cannot be called on a `Tree` node. Also note that
		unwrapping the root `Tag` node of a `Tree` might yield
		an invalid XML document that contains several roots."""
		self.delete()
		return self

	def coalesce(self):
		"""Coalesces adjacent string nodes and removes empty string
		nodes from this subtree. Has no effect on leaf nodes. In
		particular, if this is  called on an empty `String` node, this
		node will not be removed from the tree."""
		pass

class Branch(Node, list):
	"""Base class for non-leaf nodes viz. `Tree` nodes and `Tag` nodes.

	Branches are represented as lists of nodes. They support most `list`
	operations. Those that are not implemented will raise an exception if
	called.
	"""

	def __init__(self):
		super().__init__()

	@property
	def plain(self):
		return all(not isinstance(node, Tag) for node in self)

	def __iter__(self):
		return list.__iter__(self)

	def __hash__(self):
		return id(self)

	def __add__(self, value):
		ret = self.copy()
		ret.extend(value.copy())
		return ret

	def __eq__(self, value):
		raise NotImplementedError

	def __ge__(self, value):
		raise NotImplementedError

	def __gt__(self, value):
		raise NotImplementedError

	def __iadd__(self, value):
		self.extend(value.copy())

	def __imul__(self, value):
		raise NotImplementedError

	def __le__(self, value):
		raise NotImplementedError

	def __lt__(self, value):
		raise NotImplementedError

	def __mul__(self, value):
		raise NotImplementedError

	def __ne__(self, value):
		raise NotImplementedError

	def __rmul__(self, value):
		raise NotImplementedError

	def count(self, value):
		raise NotImplementedError

	def pop(self, index=-1):
		node = self[index]
		del self[index]
		return node

	def extend(self, iterable):
		for node in list(iterable):
			self.append(node)

	def coalesce(self, recursive=True):
		i = 0
		while i < len(self):
			cur = self[i]
			if isinstance(cur, String):
				if not cur.data:
					cur.delete()
				elif i < len(self) - 1 and isinstance(self[i + 1], String):
					cur.replace_with(cur.data + self[i + 1].data)
					self[i + 1].delete()
				else:
					i += 1
			elif recursive and isinstance(cur, Tag):
				cur.coalesce()
				i += 1
			else:
				i += 1

	def stuck_child(self):
		i = 0
		while i < len(self):
			node = self[i]
			match node:
				case Tag():
					return node
				case String() if node.isspace():
					pass
				case Comment() | Instruction():
					pass
				case _:
					break
			i += 1

	def index(self, node, start: SupportsIndex=0, stop: SupportsIndex=sys.maxsize):
		"""Note that we check for objects identity: we compare pointers
		instead of using __eq__. This kinda breaks semantics, but we
		want to be able to compare String nodes with the usual operator.
		"""
		start = self._translate_index(start)
		stop = self._translate_index(stop)
		while start < stop:
			if self[start] is node:
				return start
			start += 1
		raise ValueError("not found")

	def __contains__(self, node):
		"""Note that we check for objects identity. We compare pointers
		instead of using __eq__.
		"""
		for child in self:
			if child is node:
				return True
		return False

	def children(self):
		ret = []
		for node in self:
			if isinstance(node, Tag):
				ret.append(node)
		return ret

	@property
	def mixed(self):
		has_string = has_tag = False
		for node in self:
			match node:
				case Tag():
					if has_string:
						return True
					has_tag = True
				case String() if not node.isspace():
					if has_tag:
						return True
					has_string = True
		return False

	@property
	def empty(self):
		for node in self:
			match node:
				case Tag():
					return False
				case String() if not node.isspace():
					return False
		return True

	def remove(self, node):
		"Removes the given child node."
		i = self.index(node)
		del self[i]

	def clear(self):
		while len(self) > 0:
			del self[0]

	def __setitem__(self, key, value):
		assert isinstance(key, int)
		self[key].replace_with(value)

	def __delitem__(self, i):
		node = self[i]
		node._parent = None
		node.location = None
		list.__delitem__(self, i)

	def _translate_index(self, i):
		if i < 0:
			i += len(self)
			if i < 0:
				i = 0
		elif i > len(self):
			i = len(self)
		return i

	def insert(self, i, node):
		if isinstance(node, Node):
			if isinstance(node, Tree):
				for j, child in enumerate(list(node)):
					self.insert(i + j, child)
				return
			# Detach the node from the tree it belongs to, if any.
			# The node might already belong to this tree.
			node.delete()
		else:
			assert isinstance(node, str), repr(node)
			node = String(node)
		i = self._translate_index(i)
		node._parent = self
		list.insert(self, i, node)

	def append(self, node: Node | str):
		self.insert(len(self), node)

	def prepend(self, node):
		self.insert(0, node)

	def strings(self):
		ret = []
		for node in self:
			match node:
				case String():
					ret.append(node)
				case Tag():
					ret.extend(node.strings())
		return ret

class Tree(Branch):
	"""`Tree` represents the XML document proper. It must contain a single
	tag node and optionally comments and processing instructions. `Tree`
	objects constructed from files also hold blank `String` nodes for
	new lines, etc.
	"""

	def __init__(self):
		# Prevent initializing this with an iterator, because we don't
		# do this in Tag.
		super().__init__()
		self._byte_source = None
		self.location = None
		self._file = None

	def __hash__(self):
		return id(self)

	@property
	def path(self):
		return "/"

	@property
	def parent(self):
		return None

	@property
	def file(self):
		return self._file

	@property
	def root(self):
		ret = None
		for node in self:
			if isinstance(node, Tag):
				if ret is not None:
					raise Exception("multiple root tags in XML document")
				ret = node
		if ret is None:
			raise Exception("attempt to retrieve the root tag of a tree that does not have one")
		return ret

	@property
	def byte_source(self):
		return self._byte_source

	def __repr__(self):
		if self.file:
			return f"<Tree file={self.file!r}>"
		return "<Tree>"

	def text(self, **kwargs):
		return "".join(node.text(**kwargs) for node in self)

	def delete(self):
		raise Exception("nodes of type 'tree' cannot be deleted")

	def insert_before(self, node):
		raise Exception("cannot insert a node before a tree")

	def insert_after(self, node):
		raise Exception("cannot insert a node after a tree")

	def copy(self):
		ret = Tree()
		for node in self:
			ret.append(node.copy())
		return ret

	def replace_with(self, other):
		raise Exception("cannot replace Tree nodes")

class Tag(Branch):
	"""Represents element nodes.

	`Tag` objects have both a `list`-like and a `dict`-like interface.

	When they are indexed with integers, the children of the node are
	accessed. When they are indexed with strings, XML attributes are
	accessed. Indexing an attribute that the `Tag` does not possess is
	not treated as an error, and returns the empty string.

	The `in` operator also takes types into account: if a `Node` is given,
	it will check whether this node is a child of `Tag`. Otherwise, it
	assumes the argument is an attribute name, and checks whether the
	`Tag` bears this attribute.

	Iterating over a `Tag` node yields the tag's children. The methods
	`keys()`, `values()` and `items()` can be used for iterating over
	attributes.
	"""

	__match_args__ = ("name",)

	def __init__(self, name_, **attributes):
		"""The argument `name` is the name of the node as a string, e.g.
		"html". Attributes can be passed as keyword arguments with
		`**attributes` (their order is preserved, see
		https://docs.python.org/3/whatsnew/3.6.html#whatsnew36-pep468).
		"""
		super().__init__()
		self.name = name_
		self.attrs = collections.OrderedDict()
		self.problems = []
		for key, value in attributes.items():
			# Special case, for passing python keywords conveniently,
			# as in tree.Tag("span", class_="hello"), which can be
			# used instead of tree.Tag("span", **{"class": "hello"})
			if len(key) > 1 and key[-1] == "_":
				key = key[:-1]
			# So that we can use tree.Tag("span", data_tip="foo")
			# instead of tree.Tag("span", **{"data-tip": "foo"})
			key = key.replace("_", "-")
			self[key] = value

	def stuck_following_sibling(self):
		parent = self.parent
		assert parent is not None
		i = parent.index(self) + 1
		while i < len(parent):
			node = parent[i]
			match node:
				case Tag():
					return node
				case String() if node.isspace():
					pass
				case Comment() | Instruction():
					pass
				case _:
					break
			i += 1

	def stuck_preceding_sibling(self):
		parent = self.parent
		assert parent is not None
		i = parent.index(self) - 1
		while i >= 0:
			node = parent[i]
			match node:
				case Tag():
					return node
				case String() if node.isspace():
					pass
				case Comment() | Instruction():
					pass
				case _:
					break
			i -= 1

	def __hash__(self):
		return id(self)

	def copy(self):
		ret = Tag(self.name, **self.attrs)
		for child in self:
			ret.append(child.copy())
		return ret

	def keys(self):
		return self.attrs.keys()

	def values(self):
		return self.attrs.values()

	def items(self):
		return self.attrs.items()

	def __repr__(self):
		ret = f"<{self.name}"
		for k, v in self.attrs.items():
			ret += f' {k}={quote_attribute(v)}'
		ret += ">"
		return ret

	def __contains__(self, val):
		if isinstance(val, Node):
			return super().__contains__(val)
		assert isinstance(val, str)
		return val in self.attrs

	def unwrap(self):
		parent = self.parent
		i = parent.index(self)
		list.__delitem__(parent, i)
		for p, node in enumerate(self, i):
			node._parent = parent
			list.insert(parent, p, node)
		self._parent = None
		self.location = None
		list.clear(self)
		return self

	def bad(self, msg):
		self.problems.append(msg)

	@property
	def path(self):
		buf = []
		node = self
		while not isinstance(node, Tree):
			parent = node.parent
			index = 0
			for child in parent:
				if not isinstance(child, Tag):
					continue
				if child.name == node.name:
					index += 1
					if child is node:
						break
			assert index > 0
			buf.append(f"/{node.name}[{index}]")
			node = parent
		assert buf
		buf.reverse()
		return "".join(buf)

	def __getitem__(self, key):
		if isinstance(key, str):
			return self.attrs.get(key, "")
		return super().__getitem__(key)

	def __setitem__(self, key, value):
		if isinstance(key, int):
			return super().__setitem__(key, value)
		assert isinstance(key, str)
		if value is None:
			del self[key]
			return
		value = str(value)
		# Always normalize space.
		value = " ".join(value.strip().split())
		if value:
			self.attrs[key] = value
		elif key in self.attrs:
			del self.attrs[key]

	def __delitem__(self, key):
		if isinstance(key, int):
			super().__delitem__(key)
		else:
			assert isinstance(key, str)
			try:
				del self.attrs[key]
			except KeyError:
				pass

	def text(self, **kwargs):
		buf = []
		config = kwargs.copy()
		config["space"] = "preserve"
		for node in self:
			buf.append(node.text(**config))
		data = "".join(buf)
		if kwargs.get("space", "default") == "default":
			data = re.sub(r"\s+", " ", data.strip())
		return data

class String(Node, collections.UserString):
	"""Represents a text node.

	`String` nodes behave like normal `str` objects, but they can also be
	edited in-place with the following methods."""

	def clear(self):
		"Sets this `String` to the empty string."
		if self.data == "":
			return
		self.location = None
		self.data = ""

	def __hash__(self):
		return id(self)

	@property
	def plain(self):
		return True

	def strings(self):
		return [self]

	def append(self, data):
		"Adds text at the end of this `String`."
		if not data:
			return
		self.location = None
		self.data += data

	def prepend(self, data):
		"Adds text at the beginning of this `String`."
		if not data:
			return
		self.location = None
		self.data = data + self.data

	def insert(self, index, data):
		"Adds text at the given index of this `String`."
		if not data:
			return
		self.location = None
		if index < 0:
			index += len(self.data)
			if index < 0:
				index = 0
		elif index > len(self.data):
			index = len(self.data)
		self.data = self.data[:index] + data + self.data[index:]

	def text(self, **kwargs):
		data = str(self.data) # casting is necessary for String
		space = kwargs.get("space", "default")
		if space == "preserve":
			return data
		data = data.strip()
		data = re.sub(r"\s+", " ", data)
		return data

	def copy(self):
		return String(self.data)

class Comment(Node, collections.UserString):
	"""Represents a comment.

	`Comment` nodes behave like strings.
	"""

	def __repr__(self):
		return repr(self.xml())

	def copy(self):
		return Comment(self.data)

	def __hash__(self):
		return id(self)

class Instruction(Node):
	"""Represents a processing instruction.

	Initial XML declarations e.g. `<?xml version="1.0"?>` are also
	represented as processing instructions.
	"""

	def __init__(self, target, data):
		super().__init__()
		self.target = target
		self.data = data

	def __repr__(self):
		return self.xml()

	def __hash__(self):
		return id(self)

	def copy(self):
		return Instruction(self.target, self.data)

class _Parser:

	def __init__(self, source, path=None):
		self.parser = expat.ParserCreate()
		self.parser.ordered_attributes = True
		self.parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
		self.parser.buffer_text = True
		for attr in dir(self):
			if not attr[0].isupper():
				continue
			val = getattr(self, attr)
			if not callable(val):
				continue
			setattr(self.parser, attr, val)
		self.tree = Tree()
		self.stack = [self.tree]
		self.tree._byte_source = source
		self.tree._file = path
		self.tree.location = Location(0, len(source), 1, 1)
		self.last_node = None

	def parse(self):
		self.parser.Parse(self.tree.byte_source, True)
		if self.last_node:
			loc = self.last_node.location
			self.last_node.location = Location(loc.start,
				len(self.tree.byte_source),
				loc.line, loc.column)
		return self.tree

	def set_location(self, node, close=False):
		start = self.parser.CurrentByteIndex
		if self.last_node is not None:
			last = self.last_node.location
			self.last_node.location = Location(last.start, start,
				last.line, last.column)
		if not close:
			line = self.parser.CurrentLineNumber
			column = self.parser.CurrentColumnNumber
			node.location = Location(start, None, line, column)
		self.last_node = node

	def make_node(self, klass, *args, **kwargs):
		node = klass(*args, **kwargs)
		parent = self.stack[-1]
		node._parent = parent
		list.append(parent, node)
		if klass is Tag:
			self.stack.append(node)
		self.set_location(node)

	def XmlDeclHandler(self, version, encoding, standalone):
		data = ""
		if version is not None:
			data += " version=" + quote_attribute(version)
		if encoding is not None:
			data += " encoding=" + quote_attribute(encoding)
		if standalone != -1:
			data += " standalone=" + quote_attribute(
				standalone and "yes" or "no")
		self.make_node(Instruction, "xml", data[1:])

	def StartDoctypeDeclHandler(self, doctypeName, systemId,
		publicId, has_internal_subset):
		raise NotImplementedError

	def EndDoctypeDeclHandler(self):
		raise NotImplementedError

	def ElementDeclHandler(self, name, model):
		raise NotImplementedError

	def AttlistDeclHandler(self, elname, attname, type, default, required):
		raise NotImplementedError

	def StartElementHandler(self, name, attributes):
		# Drop all namespaces, in the tag name and in attributes.
		colon = name.find(":")
		if colon >= 0:
			name = name[colon + 1:]
		attrs = []
		for i in range(0, len(attributes), 2):
			key, value = attributes[i:i + 2]
			colon = key.find(":")
			if colon >= 0:
				key = key[colon + 1:]
			attrs.append((key, value))
		self.make_node(Tag, name, **dict(attrs))

	def EndElementHandler(self, name):
		node = self.stack.pop()
		self.set_location(node, close=True)

	def ProcessingInstructionHandler(self, target, data):
		self.make_node(Instruction, target, data or "")

	def CharacterDataHandler(self, data):
		assert len(data) > 0
		parent = self.stack[-1]
		if len(parent) > 0 and isinstance(parent[-1], String):
			# Need to save and restore the location because we set
			# it to None when the string is modified
			loc = parent[-1].location
			parent[-1].append(data)
			parent[-1].location = loc
		else:
			self.make_node(String, data)

	def EntityDeclHandler(self, entityName, is_parameter_entity, value,
		base, systemId, publicId, notationName):
		raise NotImplementedError

	def NotationDeclHandler(self, notationName, base, systemId, publicId):
		raise NotImplementedError

	def StartNamespaceDeclHandler(self, prefix, uri):
		raise NotImplementedError

	def EndNamespaceDeclHandler(self, prefix):
		raise NotImplementedError

	def CommentHandler(self, data):
		self.make_node(Comment, data)

	def StartCdataSectionHandler(self):
		raise NotImplementedError

	def EndCdataSectionHandler(self):
		raise NotImplementedError

	def DefaultHandler(self, data):
		if data.strip():
			raise NotImplementedError
		self.CharacterDataHandler(data)

	def NotStandaloneHandler(self):
		raise NotImplementedError

	def ExternalEntityRefHandler(self, context, base, systemId, publicId):
		raise NotImplementedError

class Error(Exception):
	"""Raised for parsing errors viz. for malformed XML files. Schema
	errors do not raise exceptions."""

	def __init__(self, line=0, column=0, text="", source=b"", path=""):
		self.path = path
		self.line = line
		self.column = column
		self.text = text
		self.source = source

	def __str__(self):
		return f"Error(path='{self.path}' line={self.line}, column={self.column}, text={repr(self.text)})"

def _xpath_glob(node, pattern, *arg):
	assert isinstance(pattern, str)
	(text,) = arg or (node.text(),)
	return fnmatch.fnmatchcase(text, pattern)

def _xpath_iglob(node, pattern, *arg):
	assert isinstance(pattern, str)
	(text,) = arg or (node.text(),)
	return fnmatch.fnmatchcase(text.lower(), pattern.lower())

def _xpath_regex(node, pattern, *arg):
	assert isinstance(pattern, str)
	(text,) = arg or (node.text(),)
	return bool(re.search(pattern, text))

def _xpath_mixed(node, *args):
	assert isinstance(node, Node)
	return node.mixed

def _xpath_empty(node, *args):
	assert isinstance(node, Node)
	return node.empty

def _xpath_plain(node, *args):
	assert isinstance(node, Node)
	return node.plain

def _xpath_name(node, *args):
	assert isinstance(node, Node)
	return isinstance(node, Tag) and node.name or None

def _xpath_text(node, *args):
	assert isinstance(node, Node)
	return node.text()

_xpath_funcs = {
	"glob": _xpath_glob,
	"iglob": _xpath_iglob,
	"regex": _xpath_regex,
	"mixed": _xpath_mixed,
	"empty": _xpath_empty,
	"plain": _xpath_plain,
	"name": _xpath_name,
	"text": _xpath_text,
}

def stuck_parent(node):
	if isinstance(node, Tree):
		return
	parent = node.parent
	if parent.stuck_child() is node:
		yield parent

def following(node):
	def inner(nodes):
		for node in nodes:
			yield node
			if isinstance(node, Tag):
				yield from inner(node)
	while not isinstance(node, Tree):
		parent = node.parent
		i = parent.index(node)
		yield from inner(parent[i + 1:])
		node = parent

def preceding(node):
	def inner(nodes):
		for node in reversed(nodes):
			yield node
			if isinstance(node, Tag):
				yield from inner(node)
	while not isinstance(node, Tree):
		parent = node.parent
		i = node.parent.index(node)
		yield from inner(parent[:i])
		node = parent

def children(node):
	assert isinstance(node, Node)
	if isinstance(node, Branch):
		for child in node:
			yield child

def descendants(node):
	assert isinstance(node, Node)
	if isinstance(node, Branch):
		for child in node:
			yield child
			if isinstance(child, Tag):
				yield from descendants(child)

def descendants_or_self(node):
	assert isinstance(node, Node)
	yield node
	if isinstance(node, Branch):
		yield from descendants(node)

def ancestors(node):
	assert isinstance(node, Node)
	while True:
		node = node.parent
		if not node:
			break
		yield node

def ancestors_or_self(node):
	assert isinstance(node, Node)
	yield node
	yield from ancestors(node)

def following_siblings(node):
	assert isinstance(node, Node)
	if isinstance(node, Tag):
		parent = node.parent
		i = parent.index(node)
		for child in parent[i + 1:]:
			if isinstance(child, Tag):
				yield child

def preceding_siblings(node):
	assert isinstance(node, Node)
	if isinstance(node, Tag):
		parent = node.parent
		i = parent.index(node)
		for child in reversed(parent[:i]):
			if isinstance(child, Tag):
				yield child

def handle_token(buf, tok):
	match len(buf):
		case 0:
			match tok.type:
				case tokenize.NEWLINE:
					pass
				case tokenize.NAME:
					buf.append(tok)
				case _:
					yield tok
		case 1:
			match tok.type:
				case tokenize.NEWLINE:
					yield buf[0]
					buf.clear()
				case tokenize.OP if tok.string == "-" and buf[0].end == tok.start:
					buf.append(tok)
				case tokenize.NAME:
					yield buf[0]
					buf[0] = tok
				case _:
					yield buf[0]
					buf.clear()
					yield tok
		case 2:
			match tok.type:
				case tokenize.NEWLINE:
					yield buf[0]
					yield buf[1]
					buf.clear()
				case tokenize.NAME if buf[1].end == tok.start:
					tok = tokenize.TokenInfo(
						type=tokenize.NAME,
						string=buf[0].string + "-" + tok.string,
						start=buf[0].start, end=tok.end, line=buf[0].line)
					buf.clear()
					buf.append(tok)
				case _:
					yield buf[0]
					yield buf[1]
					buf.clear()
					yield tok

# Like Python's tokenizer, but treats strings like "foo-bar-baz" as names, and
# also ignores newlines..
def tokenize_xpath(s):
	buf = []
	for tok in tokenize.generate_tokens(io.StringIO(s).readline):
		yield from handle_token(buf, tok)

class _Generator:

	def __init__(self):
		self.code = ""
		self.indents = []
		self.bufs = []
		self.routines_nr = 0
		self.env = {f.__name__: f
			for funcs in (_xpath_funcs.values(), (Tag, Tree, Branch,
				children,
				descendants, descendants_or_self,
				ancestors, ancestors_or_self,
				following_siblings, preceding_siblings,
				following, preceding))
				for f in funcs}
		self.search = {}
		self.match = {}

	def parse(self, expr):
		gen = tokenize_xpath(expr)
		tokenizer = Tokenizer(gen, verbose=False)
		parser = GeneratedParser(tokenizer, verbose=False)
		root = parser.start()
		if not root:
			err = parser.make_syntax_error("<xpath expression>")
			traceback.print_exception(err.__class__, err, None)
			raise err
		return root

	def append(self, line):
		self.bufs[-1].append(self.indents[-1] * "\t" + line + "\n")
		if line.startswith("def ") or line.startswith("if ") \
			or line.startswith("for "):
			self.indents[-1] += 1

	def start_routine(self):
		buf = []
		self.indents.append(0)
		self.bufs.append(buf)
		self.routines_nr += 1
		return f"xpath_expression_{self.routines_nr}"

	def end_routine(self):
		code = self.bufs.pop()
		if self.bufs:
			code.append("\n")
		self.code += "".join(code)
		self.indents.pop()

	def compile(self, expr, search=True):
		if search:
			table, main_func = self.search, self.generate_main_search
		else:
			table, main_func = self.match, self.generate_main_match
		f = table.get(expr)
		if f:
			return f
		t = self.parse(expr)
		assert isinstance(t, Path)
		main = main_func(t, expr)
		code = compile(self.code, "<xpath expression>", "exec")
		exec(code, self.env)
		f = self.env[main]
		setattr(f, "source_code", self.code)
		table[expr] = f
		self.code = ""
		self.indents.clear()
		self.bufs.clear()
		return f

	def generate(self, expr, code=None):
		match expr:
			case Path():
				name = self.start_routine()
				self.generate_path(expr, name)
				self.end_routine()
				return f"{name}(node)"
			case Step():
				self.generate_step(expr)
			case str():
				return expr
			case Op(val="or") | Op(val="and"):
				return f"bool({self.generate(expr.l)} {expr.val} {self.generate(expr.r)})"
			case Op(val="not"):
				return f"not {self.generate(expr.r)}"
			case Op():
				return f"{self.generate(expr.l)} {expr.val} {self.generate(expr.r)}"
			case Func():
				return self.generate_call(expr)
			case _:
				assert 0, "%r" % expr

	def generate_main_search(self, path, code):
		func_name = self.start_routine()
		self.append(f"def {func_name}(node):")
		self.append(repr(code))
		if path.absolute:
			self.append("node = node.tree")
		for step in path.steps:
			self.generate(step)
		self.append("yield node")
		self.end_routine()
		return func_name

	def generate_main_match(self, path, code):
		func_name = self.start_routine()
		self.append(f"def {func_name}(node):")
		self.append(repr(code))
		steps = list(reversed(path.steps))
		for i, step in enumerate(steps):
			if step.name_test:
				self.append(f"if isinstance(node, Tag) and node.name == {step.name_test!r}:")
			else:
				self.append("if isinstance(node, Tag):")
			for pred in step.predicates:
				self.append(f"if {self.generate(pred)}:")
			if i == len(steps) - 1:
				if path.absolute and step.axis == "child":
					self.append("node = node.parent")
					self.append("if isinstance(node, Tree):")
				break
			match step.axis:
				case "self":
					pass
				case "child":
					self.append("node = node.parent")
					if not step.name_test:
						self.append("if node is not None:")
				case "stuck-child":
					self.append("node = node.stuck_parent()")
					if not step.name_test:
						self.append("if node is not None:")
				case "descendant-or-self" if step.abbreviated:
					self.append("for node in ancestors_or_self(node):")
				case _:
					raise Exception(f"axis {step.axis!r} not allowed in xpath matching functions")
		self.append("return True")
		self.indents[-1] = 1
		self.append("return False")
		self.end_routine()
		return func_name

	def generate_path(self, path, func_name):
		self.append(f"def {func_name}(node):")
		if path.absolute:
			self.append("node = node.tree")
		for step in path.steps:
			self.generate(step)
		self.append("return True")
		self.indents[-1] = 1
		self.append("return False")

	def generate_step(self, step):
		match step.axis:
			case "self":
				pass
			case "child":
				self.append("for node in children(node):")
			case "descendant":
				self.append("for node in descendants(node):")
			case "descendant-or-self":
				self.append("for node in descendants_or_self(node):")
			case "parent":
				self.append("node = node.parent")
				self.append("if node is not None:")
			case "ancestor":
				self.append("for node in ancestors(node):")
			case "ancestor-or-self":
				self.append("for node in ancestors_or_self(node):")
			case "following-sibling":
				self.append("for node in following_siblings(node):")
			case "following":
				self.append("for node in following(node):")
			case "preceding-sibling":
				self.append("for node in preceding_siblings(node):")
			case "preceding":
				self.append("for node in preceding(node):")
			case "stuck-child":
				self.append("if (node := node.stuck_child()) is not None:")
			case "stuck-parent":
				self.append("if (node := node.stuck_parent()) is not None:")
			case "stuck-following-sibling":
				self.append("if (node := node.stuck_following_sibling()) is not None:")
			case "stuck-preceding-sibling":
				self.append("if (node := node.stuck_preceding_sibling()) is not None:")
			case _:
				assert 0, repr(step.axis)
		if step.name_test:
			self.append(f"if isinstance(node, Tag) and node.name == {step.name_test!r}:")
		else:
			self.append("if isinstance(node, Branch):")
		for pred in step.predicates:
			self.append(f"if {self.generate(pred)}:")

	def generate_call(self, func):
		buf = []
		f = _xpath_funcs.get(func.name)
		if not f:
			raise Exception(f"xpath function '{func.name}' not defined")
		buf.append(f"{f.__name__}(node, ")
		for i, arg in enumerate(func.args):
			buf.append(self.generate(arg))
			if i < len(func.args) - 1:
				buf.append(", ")
		buf.append(")")
		return "".join(buf)

generator = _Generator()

def term_color(code=None):
	if not code:
		return "\N{ESC}[0m"
	code = code.lstrip("#")
	assert len(code) == 6
	R = int(code[0:2], 16)
	G = int(code[2:4], 16)
	B = int(code[4:6], 16)
	return f"\N{ESC}[38;2;{R};{G};{B}m"

colors = {
	"instruction": "#aa5500",
	"comment": "#3b9511",
	"tag": "#0055ff",
	"attr-name": "#5500ff",
	"attr-value": "#5500ff",
}

def space_before_opening(node):
	assert isinstance(node, Tag)
	parent = node.parent
	if not parent:
		return False
	i = parent.index(node) - 1
	while i >= 0:
		if isinstance(parent[i], String):
			if parent[i].rstrip() != parent[i]:
				return True
			if parent[i] != "":
				return False
		elif not isinstance(parent[i], (Comment, Instruction)):
			return False
		i -= 1
	return False

def space_after_opening(node):
	assert isinstance(node, Tag)
	i = 0
	while i < len(node):
		if isinstance(node[i], String):
			if node[i].lstrip() != node[i]:
				return True
			if node[i] != "":
				return False
		elif not isinstance(node[i], (Comment, Instruction)):
			return False
		i += 1
	return False

def space_before_closing(node):
	assert isinstance(node, Tag)
	i = len(node)
	while i > 0:
		i -= 1
		if isinstance(node[i], String):
			if node[i].rstrip() != node[i]:
				return True
			if node[i] != "":
				return False
		elif not isinstance(node[i], (Comment, Instruction)):
			return False
	return False

def space_after_closing(node):
	assert isinstance(node, Tag)
	parent = node.parent
	if not parent:
		return False
	i = parent.index(node) + 1
	while i < len(parent):
		match parent[i]:
			case String() if node.data and not node.data.isspace():
				if parent[i].lstrip() != parent[i]:
					return True
				if parent[i] != "":
					return False
			case Comment() | Instruction():
				pass
			case _:
				return False
		i += 1
	return False

def tag_category(node):
	assert isinstance(node, Tag)
	if node.matches("//teiHeader//title"):
		return "xml-heading"
	match node.name:
		case "pb" | "milestone" | "lb":
			return "struct-physical"
		case "rdg":
			return "reading"
		case "sic" | "corr" | "orig" | "reg" | "foreign" | "abbr":
			return node.name
		case "hi":
			if node["rend"] == "grantha":
				return "xml-grantha"
		case "head":
			return "xml-heading"
		case _:
			return ""

def attr_name_style(node, attr):
	return ""

def attr_value_style(node, attr):
	match node.name:
		case "lg":
			if attr in ("n", "met"):
				return "attr-n"
		case "listBibl":
			if attr == "type":
				return "xml-heading"
		case "div":
			if attr == "type":
				return "xml-heading"
			if attr == "n":
				return "xml-heading"
		case _:
			if attr == "n":
				return "attr-n"
	return ""

def contents_style(node):
	return ""

class Formatter:

	def __init__(self, html=True, strip_comments=True,
		strip_instructions=False, add_xml_prefix=False,
		color=False, max_width=80 ** 10, indent_string=2 * " ",
		self_closing=True):
		# max_width is soft, not hard.
		self.indent = 0
		self.offset = 0
		self.buf = io.StringIO()
		self.html = html
		self.line_no = 0
		self.strip_comments = strip_comments
		self.color = color
		self.max_width = max_width
		self.indent_string = indent_string
		self.strip_instructions = strip_instructions
		self.add_xml_prefix = add_xml_prefix
		self.state = "wait_line"
		self.self_closing = self_closing

	def format_contents(self, node):
		for child in node:
			self.format_node(child)
		self.finish()

	def format(self, node):
		self.format_node(node)
		self.finish()

	def format_invalid(self, xml):
		self.write(xml)
		self.finish()

	def finish(self):
		match self.state:
			case "wait_end":
				if self.html:
					self.buf.write('</span>')
					self.buf.write("</div>")
				self.state = "wait_line"
			case "wait_line":
				pass
			case _:
				assert 0

	def format_node(self, node, cat=""):
		match node:
			case Tree():
				return self.format_contents(node)
			case Tag():
				return self.format_tag(node)
			case String():
				return self.format_string(node, cat)
			case Comment():
				return self.format_comment(node)
			case Instruction():
				return self.format_instruction(node)
			case _:
				assert 0

	def format_instruction(self, node):
		if self.strip_instructions:
			return
		self.write(f"<?{node.target} {node.data}?>", klass="instruction")

	def format_comment(self, node):
		if self.strip_comments:
			return
		# Escape --
		node = node.data.replace("--", "-&#45;")
		self.write(f"<!--{node}-->", klass="comment")

	def format_string(self, node, cat=""):
		node = str(node)
		self.write(quote_string(node), klass=f"string {cat}")

	def format_opening_tag(self, node, cat):
		self.write("<", klass=f"tag tag-punct {cat}")
		self.write(node.name, klass=f"tag {cat}")
		attrs = node.attrs.items()
		for k, v in attrs:
			if self.add_xml_prefix and k in ("lang", "space", "base", "id"):
				k = f"xml:{k}"
			self.write(" ")
			self.write(k, klass=f"tag attr-name {attr_name_style(node, k)}")
			self.write("=",  klass=f"tag tag-punct {cat}")
			self.write('"',  klass=f"tag tag-punct {cat}")
			self.write(escape_attribute(v), klass=f"tag attr-value {attr_value_style(node, k)}")
			self.write('"',  klass=f"tag tag-punct {cat}")
		if self.self_closing and len(node) == 0:
			self.write("/>", klass=f"tag tag-punct {cat}")
		else:
			self.write(">", klass=f"tag tag-punct {cat}")

	def format_closing_tag(self, node, cat):
		if self.self_closing and len(node) == 0:
			return
		self.write("</", klass=f"tag tag-punct {cat}")
		self.write(node.name, klass=f"tag {cat}")
		self.write(">", klass=f"tag tag-punct {cat}")

	def format_tag(self, node):
		cat = tag_category(node)
		self.format_opening_tag(node, cat)
		for child in node:
			self.format_node(child, cat)
		self.format_closing_tag(node, cat)

	def start_line(self):
		self.line_no += 1
		if self.html:
			self.buf.write('<div class="xml-line">')
			no = self.line_no
			if no == 1 or no % 5 == 0:
				pass
			else:
				no = "·"
			self.buf.write(f'<span class="xml-line-no hidden">{no}</span>')
			self.buf.write('<span class="xml-line-contents">')
		self.state = "wait_end"

	def end_line(self):
		if self.html:
			self.buf.write('\n</span>')
			self.buf.write("</div>")
		self.buf.write("\n")
		self.state = "wait_line"

	def write(self, text, klass=None):
		for chunk in re.findall(r"(?:[^\r\n]+)|(?:\r\n|\r|\n)", text):
			if chunk in ("\r", "\n", "\r\n"):
				chunk = ""
			match self.state:
				case "wait_line":
					self.start_line()
					if chunk:
						self.write_styled(chunk, klass)
					else:
						self.end_line()
				case "wait_end":
					if chunk:
						self.write_styled(chunk, klass)
					else:
						self.end_line()
				case _:
					assert 0

	def write_styled(self, text, klass):
		if klass and self.html:
			self.buf.write(f'<span class="{klass}">')
			self.buf.write(quote_string(text))
			self.buf.write('</span>')
		elif klass and self.color:
			self.buf.write(term_color(colors[klass]))
			self.buf.write(text)
			self.buf.write(term_color())
		elif self.html:
			self.buf.write(quote_string(text))
		else:
			self.buf.write(text)

	def wrote_space(self):
		return self.buf.getvalue()[-1].isspace()

	def text(self):
		return self.buf.getvalue()

def html_format(node: Node | str, skip_root=False, color=True,
	add_xml_prefix=True, strip_comments=False):
	fmt = Formatter(color=color, add_xml_prefix=add_xml_prefix,
		strip_comments=strip_comments)
	if skip_root:
		assert isinstance(node, Node)
		fmt.format_contents(node)
	elif isinstance(node, Node):
		fmt.format(node)
	else:
		assert isinstance(node, str)
		fmt.format_invalid(node)
	return fmt.text()

class Serializer:
	"Helper for building XML trees."

	def __init__(self):
		self.clear()

	def clear(self):
		self.tree = Tree()
		self.stack = [self.tree]

	def push(self, node: Node | str, **attrs):
		if isinstance(node, Node):
			assert not attrs
			node = node.copy()
		else:
			node = Tag(node, **attrs)
		self.stack.append(node)

	@property
	def top(self):
		return self.stack[-1]

	def pop(self):
		assert len(self.stack) > 1 # Should never pop the root tree.
		return self.stack.pop()

	def join(self, expect=None):
		"""Pop one node from the stack and append it to the node now
		at the top of the stack.

		`expect` is optional. If given, it should either be the node at
		the top of the stack or the element name, if it is an element.
		This is only used to detect push() and pop() that are not
		paired properly."""
		item = self.pop()
		match expect:
			case None:
				pass
			case Node():
				assert item is expect
			case str():
				assert isinstance(item, Tag) and item.name == expect
			case _:
				raise Exception(f"bad value {expect!r}")
		self.append(item)

	def append(self, node: Node | str):
		match node:
			case Tree():
				node = node.copy()
				for child in node:
					self.stack[-1].append(child)
			case Node():
				self.stack[-1].append(node.copy())
			case _:
				self.stack[-1].append(node)

	def extend(self, node_iter):
		for node in list(node_iter):
			self.append(node)


if __name__ == "__main__":
	if len(sys.argv) <= 1:
		exit()
	try:
		try:
			tree = parse(sys.argv[1])
		except Error:
			with open(sys.argv[1]) as f:
				tree = f.read()
		fmt = html_format(tree)
		sys.stdout.write(fmt)
	except (BrokenPipeError, KeyboardInterrupt):
		exit(1)
	except Error as err:
		print(err, file=sys.stderr)
