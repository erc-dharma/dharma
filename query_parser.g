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

	def _complete_fields(self, name, mode=None):
		# Resolve name and mode using inheritance ensuring empty strings are preserved
		final_name = self.name if self.name is not None else name
		final_mode = self.mode or mode
		# Apply dotted parsing to extract the mode if present
		if final_name:
			parts = final_name.split('.')
			if len(parts) > 1 and parts[-1] in {"normal", "exact", "normalized"}:
				final_mode = parts.pop()
			final_name = ".".join(parts)
		# If child is a logical node (not a string), pass the resolved name/mode down
		if not isinstance(self.child, str):
			return self.child._complete_fields(final_name, final_mode)
		# Virtual field expansion for composite lists
		if final_name == "repo":
			return Or(Field("repo_id", self.child, final_mode), Field("repo_name", self.child, final_mode))
		if final_name == "author":
			return Or(Field("author_ident", self.child, final_mode), Field("author_name", self.child, final_mode))
		if final_name == "editor":
			return Or(Field("editor_ident", self.child, final_mode), Field("editor_name", self.child, final_mode))
		if final_name == "lang":
			return Or(Field("lang_ident", self.child, final_mode), Field("lang_name", self.child, final_mode))
		if final_name == "script":
			return Or(Field("script_ident", self.child, final_mode), Field("script_name", self.child, final_mode))
		# Mapping for specific sub-fields
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
		return self

	def serialize(self):
		res = {
			"op": "field",
			"field": self.name,
			"value": self.child,
		}
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

def parse_seq_range(s):
	# Parse textual interval bounds bypassing tokenizer hyphenation logic
	if '-' not in s:
		return (0, -1)
	parts = s.split('-')
	x = int(parts[0]) if parts[0] else 0
	y = int(parts[1]) if parts[1] else -1
	return (x, y)

def mkbinop(klass, l, r):
	if isinstance(l, klass):
		l.children.append(r)
		return l
	return klass(l, r)

def mkand(*elems):
	return mkbinop(And, *elems)

def mkor(*elems):
	return mkbinop(Or, *elems)

def mkmerge(*elems):
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
	| r=OrExpr ("or" | "OR") s=AndExpr { mkor(r, s) }
	| AndExpr

AndExpr:
	| r=AndExpr ("and" | "AND") s=NearExpr { mkand(r, s) }
	| NearExpr

NearExpr:
	| r=NearExpr op=NearOp s=SeqExpr { Near(r, s, op[0], op[1]) }
	| SeqExpr

NearOp:
	| ("near" | "NEAR") '[' range=NAME ']' { parse_seq_range(range.string) }
	| ("near" | "NEAR") { (0, -1) }

SeqExpr:
	| r=SeqExpr op=SeqOp s=NotExpr { Seq(r, s, op[0], op[1]) }
	| NotExpr

SeqOp:
	| ("seq" | "SEQ") '[' range=NAME ']' { parse_seq_range(range.string) }
	| ("seq" | "SEQ") { (0, -1) }

NotExpr:
	| ("not" | "NOT") r=NotExpr { Not(r) }
	| FieldExpr

Text: r=DottedName { r }

FieldName:
	| '.' r=DottedName { "." + r }
	| DottedName

DottedName:
	| r=NAME '.' s=DottedName { r.string + "." + s }
	| r=NAME { r.string }
