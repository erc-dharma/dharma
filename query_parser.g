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

class Not(Node):

	def __init__(self, child=None):
		self.child = child

	def __repr__(self):
		buf = "(not "
		buf += repr(self.child)
		buf += ")"
		return buf

class Field(Node):

	def __init__(self, name, child=None):
		self.name = name
		self.child = child

	def __repr__(self):
		return f"{self.name}:{self.child!r}"

class _Null(Node):

	def __repr__(self):
		return "<null>"

Null = _Null()

def mkbinop(klass, l, r):
	if isinstance(l, klass):
		l.children.append(r)
		return l
	elif isinstance(r, klass):
		r.children.append(l)
		return r
	return And(l, r)

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

start: r=Exprs $ { r }

Exprs: r=FieldExpr+ { mkmerge(*r) }

FieldExpr:
	| name=Text ':' r=BoolExpr { Field(name, r) }
	| BoolExpr

BoolExpr:
	| '(' r=OrExpr ')' { r }
	| OrExpr

OrExpr:
	| r=OrExpr "or" s=AndExpr { mkor(r, s) }
	| AndExpr

AndExpr:
	| r=AndExpr "and" s=NotExpr { mkand(r, s) }
	| NotExpr

NotExpr:
	| "not" r=NotExpr { Not(r) }
	| Text

Text:
	| r=STRING { r.string }
	| r=NAME { r.string }
