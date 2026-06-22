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

class Field(Node):
	def __init__(self, name, child=None, mode=None):
		self.name = name
		self.mode = mode
		self.child = child

	def __repr__(self):
		mode_str = f"[{self.mode}]" if self.mode else ""
		return f"{self.name or '<null>'}{mode_str}:{self.child!r}"

	def _resolve_name_mode(self, name, mode):
		final_name = self.name if self.name is not None else name
		final_mode = self.mode or mode
		if final_name:
			parts = final_name.split('.')
			if len(parts) > 1 and parts[-1] in {"normal", "exact", "normalized"}:
				final_mode = parts.pop()
			final_name = ".".join(parts)
		return final_name, final_mode

	def _expand_virtual(self, name, mode):
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
	| r=OrExpr 'OR' s=AndExpr { mkor(r, s) }
	| AndExpr

AndExpr:
	| r=AndExpr 'AND' s=NotExpr { mkand(r, s) }
	| NotExpr

NotExpr:
	| 'NOT' r=NotExpr { Not(r) }
	| FieldExpr

Text: r=DottedName { r }

FieldName:
	| '.' r=DottedName { "." + r }
	| DottedName

DottedName:
	| r=NAME '.' s=DottedName { r.string + "." + s }
	| r=NAME { r.string }
