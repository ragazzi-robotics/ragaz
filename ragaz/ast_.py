"""
Contains classes for all the syntax tree node types used in the parser.

All classes have a `pos` field containing location information. It can be None in nodes that have been inserted by the
compiler. Classes should have a `nodes` attribute containing a sequence of properties that either contain another
AST (abstract syntax tree) node or a list of AST nodes, so we can walk the tree somehow.

Some node types are defined in other modules:

- module: Global
- blocks: SetOffset, SetAttribute, SetElement, Branch, CondBranch, Phi, LandingPad
- typing: Init

For files containing source code, a File node is at the root of the tree.
"""
import ast
import sys
from ragaz import util, types_ as types

# Base class


class Registry(type):
    types = []

    def __init__(cls, name, bases, dict):
        Registry.types.append(cls)


class Node(util.Repr):
    __metaclass__ = Registry

    def __init__(self, pos, id=None):
        self.pos = pos
        self.id = id


class Name(Node):

    def __init__(self, pos, name):
        Node.__init__(self, pos)
        self.name = name


class Expression(Node):

    def __init__(self, pos):
        Node.__init__(self, pos)
        self.type = None
        self.must_escape = False
        self.is_literal = False


# literals-level

class NoneVal(Expression):

    def __init__(self, pos):
        Expression.__init__(self, pos)


class Byte(Expression):

    def __init__(self, pos, value):
        Expression.__init__(self, pos)
        value = value[1:-1]  # Remove the single quotes
        self.literal = ord(value)
        self.is_literal = True


class Bool(Expression):

    def __init__(self, pos, value):
        Expression.__init__(self, pos)
        self.literal = True if value == "True" else False
        self.is_literal = True


class Int(Expression):

    def __init__(self, pos, value):
        Expression.__init__(self, pos)
        self.literal = int(value)
        self.is_literal = True


class Float(Expression):

    def __init__(self, pos, value):
        Expression.__init__(self, pos)
        self.is_literal = True
        self.literal = float(value)
        self.is_literal = True


class Array(Expression):

    def __init__(self, pos, typ, num_elements):
        Expression.__init__(self, pos)
        self.target_type = typ
        self.num_elements = num_elements


class String(Expression):

    def __init__(self, pos, value):
        Expression.__init__(self, pos)
        if sys.version_info[0] < 3:
            self.literal = value.decode("string_escape")
        else:
            self.literal = value.encode("utf-8").decode("unicode_escape")


class MultilineString(Expression):

    def __init__(self, pos, value):
        Expression.__init__(self, pos)
        if sys.version_info[0] < 3:
            self.literal = value.decode("string_escape")
        else:
            self.literal = value.encode("utf-8").decode("unicode_escape")


# types-level

class Type(Expression):

    def __init__(self, pos, name):
        Node.__init__(self, pos)
        self.name = name


class DerivedType(Expression):

    def __init__(self, pos, name, types):
        Expression.__init__(self, pos)
        self.name = name
        self.types = types


class Mutable(Expression):

    def __init__(self, pos, value):
        Expression.__init__(self, pos)
        self.value = value


class FunctionType(Expression):

    def __init__(self, pos, ret_type, args_types):
        Node.__init__(self, pos)
        self.ret_type = ret_type
        self.args_types = args_types

        self.ir = None


class VariadicArgs(Node):

    def __init__(self, pos):
        Node.__init__(self, pos)


# Expression-level

class Reference(Expression):

    def __init__(self, pos, value):
        Expression.__init__(self, pos)
        self.value = value


class Dereference(Expression):

    def __init__(self, pos, value):
        Expression.__init__(self, pos)
        self.value = value


class Symbol(Expression):

    def __init__(self, pos, name, typ=None, internal_name=None, derivation_types=None):
        Expression.__init__(self, pos)
        self.name = name
        self.internal_name = internal_name
        self.type = typ
        self.derivation_types = derivation_types
        self.check_move = False

    def get_name(self):
        return self.internal_name if self.internal_name is not None else self.name

    def is_hidden(self):
        return self.get_name().startswith("hidden$")


class Offset(Expression):

    def __init__(self, pos, obj, idx):
        Expression.__init__(self, pos)
        self.obj = obj
        self.idx = idx


class Attribute(Expression):

    def __init__(self, pos, obj, attribute):
        Expression.__init__(self, pos)
        self.obj = obj
        self.attribute = attribute
        self.derivation_types = None
        self.check_move = False

    def get_name(self):
        if isinstance(self.obj, Attribute):
            obj_name = self.get_name()
        else:
            if isinstance(self.obj, Call):
                raise
            obj_name = self.obj.get_name()
        return obj_name, self.attribute


class Element(Expression):

    def __init__(self, pos, obj, key):
        Expression.__init__(self, pos)
        self.obj = obj
        self.key = key
        self.check_copy = False

    def get_name(self):
        obj_name = self.obj.get_name()
        return obj_name


class Tuple(Expression):

    def __init__(self, pos, elements):
        Expression.__init__(self, pos)
        self.elements = elements


class List(Expression):

    def __init__(self, pos, elements=None):
        Expression.__init__(self, pos)
        self.elements = elements


class Dict(Expression):

    def __init__(self, pos, elements=None):
        Expression.__init__(self, pos)
        self.elements = elements


class Set(Expression):

    def __init__(self, pos, elements):
        Expression.__init__(self, pos)
        self.elements = elements


class Neg(Expression):

    def __init__(self, pos, value):
        Expression.__init__(self, pos)
        self.op = "-"
        self.value = value


class Add(Expression):

    def __init__(self, pos, left, right):
        Expression.__init__(self, pos)
        self.op = "+"
        self.left = left
        self.right = right


class Sub(Expression):

    def __init__(self, pos, left, right):
        Expression.__init__(self, pos)
        self.op = "-"
        self.left = left
        self.right = right


class Mul(Expression):

    def __init__(self, pos, left, right):
        Expression.__init__(self, pos)
        self.op = "*"
        self.left = left
        self.right = right


class Div(Expression):

    def __init__(self, pos, left, right):
        Expression.__init__(self, pos)
        self.op = "/"
        self.left = left
        self.right = right


class FloorDiv(Expression):

    def __init__(self, pos, left, right):
        Expression.__init__(self, pos)
        self.op = "//"
        self.left = left
        self.right = right


class Mod(Expression):

    def __init__(self, pos, left, right):
        Expression.__init__(self, pos)
        self.op = "%"
        self.left = left
        self.right = right


class Pow(Expression):

    def __init__(self, pos, left, right):
        Expression.__init__(self, pos)
        self.op = "**"
        self.left = left
        self.right = right


class BwNot(Expression):

    def __init__(self, pos, value):
        Expression.__init__(self, pos)
        self.op = "~"
        self.value = value


class BwAnd(Expression):

    def __init__(self, pos, left, right):
        Expression.__init__(self, pos)
        self.op = "&"
        self.left = left
        self.right = right


class BwOr(Expression):

    def __init__(self, pos, left, right):
        Expression.__init__(self, pos)
        self.op = "|"
        self.left = left
        self.right = right


class BwXor(Expression):

    def __init__(self, pos, left, right):
        Expression.__init__(self, pos)
        self.op = "^"
        self.left = left
        self.right = right


class BwShiftLeft(Expression):

    def __init__(self, pos, left, right):
        Expression.__init__(self, pos)
        self.op = "<<"
        self.left = left
        self.right = right


class BwShiftRight(Expression):

    def __init__(self, pos, left, right):
        Expression.__init__(self, pos)
        self.op = ">>"
        self.left = left
        self.right = right


class Not(Expression):

    def __init__(self, pos, value):
        Expression.__init__(self, pos)
        self.op = "not"
        self.value = value


class And(Expression):

    def __init__(self, pos, left, right):
        Expression.__init__(self, pos)
        self.op = "and"
        self.left = left
        self.right = right


class Or(Expression):

    def __init__(self, pos, left, right):
        Expression.__init__(self, pos)
        self.op = "or"
        self.left = left
        self.right = right


class Equal(Expression):

    def __init__(self, pos, left, right):
        Expression.__init__(self, pos)
        self.op = "=="
        self.left = left
        self.right = right


class NotEqual(Expression):

    def __init__(self, pos, left, right):
        Expression.__init__(self, pos)
        self.op = "!="
        self.left = left
        self.right = right


class LowerThan(Expression):

    def __init__(self, pos, left, right):
        Expression.__init__(self, pos)
        self.op = "<"
        self.left = left
        self.right = right


class LowerEqual(Expression):

    def __init__(self, pos, left, right):
        Expression.__init__(self, pos)
        self.op = "<="
        self.left = left
        self.right = right


class GreaterThan(Expression):

    def __init__(self, pos, left, right):
        Expression.__init__(self, pos)
        self.op = ">"
        self.left = left
        self.right = right


class GreaterEqual(Expression):

    def __init__(self, pos, left, right):
        Expression.__init__(self, pos)
        self.op = ">="
        self.left = left
        self.right = right


class Is(Expression):

    def __init__(self, pos, left, right):
        Expression.__init__(self, pos)
        self.left = left
        self.right = right


class As(Expression):

    def __init__(self, pos, left, right):
        Expression.__init__(self, pos)
        self.left = left
        self.right = right


class In(Expression):

    def __init__(self, pos, left, right):
        Expression.__init__(self, pos)
        self.left = left
        self.right = right


class Call(Expression):

    def __init__(self, pos, callable, args):
        Expression.__init__(self, pos)
        self.callable = callable
        self.fn = None
        self.args = args
        self.virtual = None
        self.call_branch = None


class NamedArg(Expression):

    def __init__(self, pos, name, value):
        Expression.__init__(self, pos)
        self.name = name
        self.value = value


class IsInstance(Expression):

    def __init__(self, pos, obj, types):
        Expression.__init__(self, pos)
        self.obj = obj
        self.types = types


class SizeOf(Expression):

    def __init__(self, pos, typ):
        Expression.__init__(self, pos)
        self.target_type = typ


class Transmute(Expression):

    def __init__(self, pos, obj, typ):
        Expression.__init__(self, pos)
        self.obj = obj
        self.type = typ


class ReallocMemory(Expression):

    def __init__(self, pos, obj, num_elements):
        Expression.__init__(self, pos)
        self.obj = obj
        self.num_elements = num_elements


class CopyMemory(Expression):

    def __init__(self, pos, src, dst, num_elements):
        Expression.__init__(self, pos)
        self.src = src
        self.dst = dst
        self.num_elements = num_elements


class MoveMemory(Expression):

    def __init__(self, pos, src, dst, num_elements):
        Expression.__init__(self, pos)
        self.src = src
        self.dst = dst
        self.num_elements = num_elements


class SetTypeAliases(Expression):

    def __init__(self, pos, aliases, types):
        Expression.__init__(self, pos)
        self.aliases = aliases
        self.types = types


# Statement-level

class Assign(Node):

    def __init__(self, pos, left, right):
        Node.__init__(self, pos)
        self.left = left
        self.right = right


class Inplace(Node):

    def __init__(self, pos, operation):
        Node.__init__(self, pos)
        self.operation = operation


class VariableDeclaration(Node):

    def __init__(self, pos, variables, assignment=None):
        Node.__init__(self, pos)
        self.variables = variables
        self.assignment = assignment


class Raise(Node):

    def __init__(self, pos, value):
        Node.__init__(self, pos)
        self.value = value
        self.call_branch = None


class Del(Node):

    def __init__(self, pos, obj):
        Node.__init__(self, pos)
        self.obj = obj


class Yield(Node):

    def __init__(self, pos, value):
        Node.__init__(self, pos)
        self.value = value


class Suite(Node):

    def __init__(self, pos, statements):
        Node.__init__(self, pos)
        self.statements = statements


class Argument(Node):

    def __init__(self, pos, name, typ=None, default_value=None, internal_name=None):
        Node.__init__(self, pos)
        self.name = name
        self.internal_name = internal_name
        self.type = typ
        self.default_value = default_value

    def get_name(self):
        return self.internal_name if self.internal_name is not None else self.name


class TryBlock(Node):

    def __init__(self, pos, suite, handler):
        Node.__init__(self, pos)
        self.suite = suite
        self.catch = [handler]


class Except(Node):

    def __init__(self, pos, typ, suite):
        Node.__init__(self, pos)
        self.type = typ
        self.suite = suite


class Function(Node):

    def __init__(self, pos, decorators, name, type_vars, args, ret):
        Node.__init__(self, pos)
        self.name = name
        self.type_vars = type_vars
        self.args = args
        self.ret = ret
        self.suite = None

        # Validate the function's decorators
        allowed_decorators = ["inline", "extern_c"]
        self.is_inline = False
        self.is_extern_c = False
        for decorator in decorators:
            if decorator.name not in allowed_decorators:
                msg = (decorator.pos, "decorator '{decorator}' not recognized".format(decorator=decorator.name))
                hints = ["Check whether there is a typo in the name."]
                raise util.Error([msg], hints=hints)
            elif decorator.name == "inline":
                self.is_inline = True
            elif decorator.name == "extern_c":
                self.is_extern_c = True

        self.is_generator = None
        self.has_context = None
        self.is_non_specialized = None
        self.self_type = None
        self.internal_name = None
        self.suffix_count = 0
        self.flow = None
        self.ir = None

        self.passes = []

    def get_name(self):
        return self.internal_name if self.internal_name is not None else self.name

    def get_all_type_vars(self):
        type_vars = {}
        type_vars.update(self.type_vars)
        if self.self_type is not None:
            type_vars.update(self.self_type.type_vars)
        return type_vars

    def generate_suffix(self):
        self.suffix_count += 1
        return "${suffix}".format(suffix=self.suffix_count - 1)


class Break(Node):
    pass


class Continue(Node):
    pass


class Pass(Node):
    pass


class Return(Node):

    def __init__(self, pos, value):
        Node.__init__(self, pos)
        self.value = value


class Ternary(Expression):

    def __init__(self, pos, cond, values):
        Expression.__init__(self, pos)
        self.cond = cond
        self.values = values


class If(Node):

    def __init__(self, pos, parts):
        Node.__init__(self, pos)
        self.parts = parts


class Import(Node):

    def __init__(self, pos, path, path_alias=None, objects=None):
        Node.__init__(self, pos)
        self.path = path
        self.path_alias = path_alias
        self.objects = objects
        self.file = None


class ImportPath(Expression):

    def __init__(self, pos, names):
        Expression.__init__(self, pos)
        self.names = names


class For(Node):

    def __init__(self, pos, loop_var, source, suite):
        Node.__init__(self, pos)
        self.source = source
        self.loop_var = loop_var
        self.suite = suite
        self.loop_jumpers = {"continue": [],
                             "break": []}


class While(Node):

    def __init__(self, pos, cond, suite):
        Node.__init__(self, pos)
        self.cond = cond
        self.suite = suite
        self.loop_jumpers = {"continue": [],
                             "break": []}


class TypeVar(Node):

    def __init__(self, pos, name):
        Node.__init__(self, pos)
        self.name = name


class Class(Node):

    def __init__(self, pos, decor, name, type_vars, attributes, methods):
        Node.__init__(self, pos)
        self.decor = decor
        self.name = name
        self.type_vars = type_vars
        self.attributes = attributes
        self.methods = methods


class Trait(Node):

    def __init__(self, pos, decor, name, type_vars, methods):
        Node.__init__(self, pos)
        self.decor = decor
        self.name = name
        self.type_vars = type_vars
        self.methods = methods


class Init(Expression):
    """
    This is used as first argument of initialization method for a class to indicate `self` instance.
    """

    def __init__(self, typ):
        Expression.__init__(self, None)
        self.type = typ


class File(Node):

    def __init__(self, suite):
        self.suite = suite
