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

	def _complete_fields(self, name, mode=None):
		# Resolve name and mode using inheritance
		final_name = self.name or name
		final_mode = self.mode or mode

		# Apply dotted parsing to extract the mode if present
		if final_name:
			parts = final_name.split('.')
			if len(parts) > 1 and parts[-1] in {"strict", "normalized"}:
				final_mode = parts.pop()
			final_name = ".".join(parts)

		# If child is a logical node (not a string), pass the resolved name/mode down
		# and discard this intermediate Field node.
		if not isinstance(self.child, str):
			return self.child._complete_fields(final_name, final_mode)

		# --- From here, we are a leaf node containing a search string ---

		# Virtual field expansion for "repo"
		if final_name == "repo":
			# Return an OR node containing the two sub-fields
			return Or(
				Field("repo_id", self.child, final_mode),
				Field("repo_name", self.child, final_mode)
			)

		# Mapping for specific sub-fields
		if final_name == "repo.ident":
			final_name = "repo_id"
		elif final_name == "repo.name":
			final_name = "repo_name"

		self.name = final_name
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
	| name=DottedName (':' | '=') r=PrimaryExpr { Field(name, r) }
	| PrimaryExpr

PrimaryExpr:
	| '(' r=Expr ')' { r }
	| r=Text { Field(None, r) }

OrExpr:
	| r=OrExpr ("or" | "OR") s=AndExpr { mkor(r, s) }
	| AndExpr

AndExpr:
	| r=AndExpr ("and" | "AND") s=NotExpr { mkand(r, s) }
	| NotExpr

NotExpr:
	| ("not" | "NOT") r=NotExpr { Not(r) }
	| FieldExpr

Text: r=DottedName { r }

DottedName:
	| r=NAME '.' s=DottedName { r.string + "." + s }
	| r=NAME { r.string }
