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

	def _complete_fields(self, name):
		for i, child in enumerate(self.children):
			self.children[i] = child._complete_fields(name)
		return self

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

	def _complete_fields(self, name):
		for i, child in enumerate(self.children):
			self.children[i] = child._complete_fields(name)
		return self

class Not(Node):

	def __init__(self, child=None):
		self.child = child

	def __repr__(self):
		buf = "(not "
		buf += repr(self.child)
		buf += ")"
		return buf

	def _complete_fields(self, name):
		self.child = self.child._complete_fields(name)
		return self

class Field(Node):

	def __init__(self, name, child=None):
		self.name = name
		self.child = child

	def __repr__(self):
		return f"{self.name or '<null>'}:{self.child!r}"

	def _complete_fields(self, name):
		if not self.name:
			self.name = name
		if isinstance(self.child, str):
			return self
		return self.child._complete_fields(self.name)

class _Null(Node):

	def __repr__(self):
		return "<null>"

	def _complete_fields(self, name):
		return self

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

start: r=Exprs $ { r._complete_fields("_default") }

Exprs: r=Expr* { mkmerge(*r) }

Expr: OrExpr

FieldExpr:
	| name=Text (':' | '=') r=PrimaryExpr { Field(name, r) }
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

Text: r=NAME { r.string }
