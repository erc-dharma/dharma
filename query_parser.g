@subheader'''

class Node:

	pass

class And(Node):

	def __init__(self, *children):
		self.children = list(children)

	def __repr__(self):
		buf = "(and "
		sep = ""
		for child in self.children:
			buf += sep + repr(child)
			sep = " "
		buf += ")"
		return buf

	def _complete_fields(self, name, mode=None):
		for i, child in enumerate(self.children):
			self.children[i] = child._complete_fields(name, mode)
		return self

	def serialize(self):
		return {
			"op": "and",
			"args": [c.serialize() for c in self.children],
		}

class Or(Node):

	def __init__(self, *children):
		self.children = list(children)

	def __repr__(self):
		buf = "(or "
		sep = ""
		for child in self.children:
			buf += sep + repr(child)
			sep = " "
		buf += ")"
		return buf

	def _complete_fields(self, name, mode=None):
		for i, child in enumerate(self.children):
			self.children[i] = child._complete_fields(name, mode)
		return self

	def serialize(self):
		return {
			"op": "or",
			"args": [c.serialize() for c in self.children],
		}

class Not(Node):

	def __init__(self, child=None):
		self.child = child

	def __repr__(self):
		buf = "(not "
		buf += repr(self.child)
		buf += ")"
		return buf

	def _complete_fields(self, name, mode=None):
		self.child = self.child._complete_fields(name, mode)
		return self

	def serialize(self):
		return {"op": "not", "arg": self.child.serialize()}

class Seq(Node):

	def __init__(self, left, right, x=0, y=-1):
		self.left = left
		self.right = right
		self.x = x
		self.y = y

	def __repr__(self):
		return f"(seq [{self.x}-{self.y}] {self.left!r} {self.right!r})"

	def _complete_fields(self, name, mode=None):
		# Validate that sequence operands are strictly textual leaves or nested sequences
		for child in (self.left, self.right):
			if not isinstance(child, (Field, Seq, Near)):
				raise ValueError("SEQ operands must be simple strings")
			if isinstance(child, Field) and child.name is not None:
				raise ValueError("SEQ operands cannot have explicit fields")
		self.left = self.left._complete_fields(name, mode)
		self.right = self.right._complete_fields(name, mode)
		return self

	def serialize(self):
		return {
			"op": "seq",
			"x": self.x,
			"y": self.y,
			"args": [self.left.serialize(), self.right.serialize()],
		}

class Near(Node):

	def __init__(self, left, right, x=0, y=-1):
		self.left = left
		self.right = right
		self.x = x
		self.y = y

	def __repr__(self):
		return f"(near [{self.x}-{self.y}] {self.left!r} {self.right!r})"

	def _complete_fields(self, name, mode=None):
		# Validate that near operands conform to adjacency constraints
		for child in (self.left, self.right):
			if not isinstance(child, (Field, Seq, Near)):
				raise ValueError("NEAR operands must be simple strings")
			if isinstance(child, Field) and child.name is not None:
				raise ValueError("NEAR operands cannot have explicit fields")
		self.left = self.left._complete_fields(name, mode)
		self.right = self.right._complete_fields(name, mode)
		return self

	def serialize(self):
		return {
			"op": "near",
			"x": self.x,
			"y": self.y,
			"args": [self.left.serialize(), self.right.serialize()],
		}

class Field(Node):

	def __init__(self, name, child=None, mode=None):
		self.name = name
		self.mode = mode
		self.child = child

	def __repr__(self):
		mode_str = f"[{self.mode}]" if self.mode else ""
		return f"{self.name or '<null>'}{mode_str}:{self.child!r}"

	def _resolve_name_mode(self, name, mode):
		# Extracted helper to keep functions short and modular
		final_name = self.name if self.name is not None else name
		final_mode = self.mode or mode
		if final_name:
			parts = final_name.split('.')
			if len(parts) > 1 and parts[-1] in {"normal", "exact", "normalized"}:
				final_mode = parts.pop()
			final_name = ".".join(parts)
		return final_name, final_mode

	def _expand_virtual(self, name, mode):
		# Extracted virtual field conditional checks to stay under length limits
		if name == "repo":
			return Or(Field("repo_id", self.child, mode), Field("repo_name", self.child, mode))
		if name == "author":
			return Or(Field("author_ident", self.child, mode), Field("author_name", self.child, mode))
		if name == "editor":
			return Or(Field("editor_ident", self.child, mode), Field("editor_name", self.child, mode))
		if name == "lang":
			return Or(Field("lang_ident", self.child, mode), Field("lang_name", self.child, mode))
		if name == "script":
			return Or(Field("script_ident", self.child, mode), Field("script_name", self.child, mode))
		return None

	def _complete_fields(self, name, mode=None):
		# Process name and mode using resolution and expansion helper functions
		final_name, final_mode = self._resolve_name_mode(name, mode)
		virtual_node = self._expand_virtual(final_name, final_mode)
		if virtual_node:
			return virtual_node._complete_fields("", None)
		mapping = {
			"repo.ident": "repo_id",
			"repo.name": "repo_name",
			"author.ident": "author_ident",
			"author.name": "author_name",
			"editor.ident": "editor_ident",
			"editor.name": "editor_name",
			"lang.ident": "lang_ident",
			"lang.name": "lang_name",
			"script.ident": "script_ident",
			"script.name": "script_name"
		}
		self.name = mapping.get(final_name, final_name)
		self.mode = final_mode
		if not isinstance(self.child, str):
			self.child = self.child._complete_fields("", final_mode)
		return self

	def serialize(self):
		# Serialize field node nesting sub-query if child is a logical node object
		res = {
			"op": "field",
			"field": self.name,
		}
		if isinstance(self.child, Node):
			res["arg"] = self.child.serialize()
		else:
			res["value"] = self.child
		if self.mode:
			res["mode"] = self.mode
		return res

class _Null(Node):

	def __repr__(self):
		return "<null>"

	def _complete_fields(self, name, mode=None):
		return self

	def serialize(self):
		return {"op": "null"}

Null = _Null()

def parse_distance(s):
	# Extract and parse a numeric distance from a string or node
	try:
		if hasattr(s, "string"): s = s.string
		clean_s = str(s).replace("/", "").strip()
		return (0, int(clean_s))
	except (ValueError, TypeError):
		return (0, -1)

def mkbinop(klass, l, r):
	# Instantiate or append to a binary operation node
	if isinstance(l, klass):
		l.children.append(r)
		return l
	return klass(l, r)

def mkand(*elems):
	# Generate an AND logical node
	return mkbinop(And, *elems)

def mkor(*elems):
	# Generate an OR logical node
	return mkbinop(Or, *elems)

def mkmerge(*elems):
	# Merge multiple logical elements correctly
	match len(elems):
		case 0:
			return Null
		case 1:
			return elems[0]
		case 2:
			return mkand(*elems)
		case _:
			return And(*elems)

'''

start: r=Exprs $ { r._complete_fields("", None) }

Exprs: r=Expr* { mkmerge(*r) }

Expr: OrExpr

FieldExpr:
	| name=FieldName (':' | '=') r=PrimaryExpr { Field(name, r) }
	| PrimaryExpr

PrimaryExpr:
	| '(' r=Exprs ')' { r }
	| r=Text { Field(None, r) }

OrExpr:
	| r=OrExpr 'OR' s=AndExpr { mkor(r, s) }
	| AndExpr

AndExpr:
	| r=AndExpr 'AND' s=NotExpr { mkand(r, s) }
	| NotExpr

# Shifted NOT precedence below NEAR and SEQ so that NOT binds to entire sequence/proximity blocks.
# This prevents logical value errors where NOT was incorrectly treated as a simple textual leaf.
NotExpr:
	| 'NOT' r=NotExpr { Not(r) }
	| NearExpr

# NearExpr now evaluates expressions derived from SeqExpr, binding higher than NOT.
NearExpr:
	| r=NearExpr op=NearOp s=SeqExpr { Near(r, s, op[0], op[1]) }
	| SeqExpr

NearOp:
	| 'NEAR' "/" dist=NUMBER { parse_distance(dist.string) }
	| 'NEAR' { (0, -1) }

# SeqExpr now directly evaluates FieldExpr, giving proximity and sequence constraints maximum priority.
SeqExpr:
	| r=SeqExpr op=SeqOp s=FieldExpr { Seq(r, s, op[0], op[1]) }
	| FieldExpr

SeqOp:
	| 'SEQ' "/" dist=NUMBER { parse_distance(dist.string) }
	| 'SEQ' { (0, -1) }

Text: r=DottedName { r }

FieldName:
	| '.' r=DottedName { "." + r }
	| DottedName

DottedName:
	| r=NAME '.' s=DottedName { r.string + "." + s }
	| r=NAME { r.string }
