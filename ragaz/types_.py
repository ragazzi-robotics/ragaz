"""
This file contains important code to the compiler handles types.

All types are classified into Base, Template, and Trait:
    - Bases: are handled as concrete types.
    - Templates: are not concrete types, but concrete types are generated from their derivations
    - Traits: are a kind of interface for virtual methods which are related to real methods of concrete types.

Furthermore, this file contains extra data to the types specified in the '__builtins__' file. For example, the
'__builtins__' file contains the structure of 'i32' type and some methods, but details like its IR representation,
size, etc., only will be found here.

Furthermore, it also contains functions to create objects (derived functions or types) from templates.
"""

import copy
import platform
from collections import OrderedDict
from llvmlite import ir
from ragaz import ast_ as ast, util

WORD_SIZE = int(platform.architecture()[0][:2])

# The default integer is `int`, which is platform dependent while the default floating is `float` which is
# 64 bits; 32 and 64 bits have similar performance but float 64 bits store better precision
BASIC = {
    "void": {"group": "void", "signed": None, "num_bits": None, "ir": ir.VoidType()},
    "anytype": {"group": "any", "signed": None, "num_bits": None, "ir": None},
    "anyint": {"group": "integer", "signed": None, "num_bits": None, "ir": None},
    "anyfloat": {"group": "floating", "signed": None, "num_bits": None, "ir": None},
    "bool": {"group": "boolean", "signed": True, "num_bits": 1, "ir": ir.IntType(1)},
    "byte": {"group": "integer", "signed": False, "num_bits": 8, "ir": ir.IntType(8)},
    "i8": {"group": "integer", "signed": True, "num_bits": 8, "ir": ir.IntType(8)},
    "u8": {"group": "integer", "signed": False, "num_bits": 8, "ir": ir.IntType(8)},
    "i16": {"group": "integer", "signed": True, "num_bits": 16, "ir": ir.IntType(16)},
    "u16": {"group": "integer", "signed": False, "num_bits": 16, "ir": ir.IntType(16)},
    "i32": {"group": "integer", "signed": True, "num_bits": 32, "ir": ir.IntType(32)},
    "u32": {"group": "integer", "signed": False, "num_bits": 32, "ir": ir.IntType(32)},
    "i64": {"group": "integer", "signed": True, "num_bits": 64, "ir": ir.IntType(64)},
    "u64": {"group": "integer", "signed": False, "num_bits": 64, "ir": ir.IntType(64)},
    "i128": {"group": "integer", "signed": True, "num_bits": 128, "ir": ir.IntType(128)},
    "u128": {"group": "integer", "signed": False, "num_bits": 128, "ir": ir.IntType(128)},
    "int": {"group": "integer", "signed": True, "num_bits": WORD_SIZE, "ir": ir.IntType(WORD_SIZE)},
    "uint": {"group": "integer", "signed": False, "num_bits": WORD_SIZE, "ir": ir.IntType(WORD_SIZE)},
    "f32": {"group": "floating", "signed": True, "num_bits": 32, "ir": ir.FloatType()},
    "f64": {"group": "floating", "signed": True, "num_bits": 64, "ir": ir.DoubleType()},
    "float": {"group": "floating", "signed": True, "num_bits": 64, "ir": ir.DoubleType()},
}

SIGNED_INTEGERS = set()
UNSIGNED_INTEGERS = set()
INTEGERS = set()
FLOATS = set()

VOID_FUNCTIONS = {"__init__", "__del__"}

MAX_TUPLE_ELEMENTS = 8


def is_wrapped(typ):
    """
    Check if type is wrapped inside in a container, ie a pointer in the stack or heap memory
    """
    res = isinstance(typ, Wrapper)
    return res


def is_heap_owner(typ):
    """
    Check if type is about ownership to data allocated in the heap memory
    """
    return hasattr(typ, "is_heap_owner") and typ.is_heap_owner


def is_reference(typ):
    """
    Check if type is about referencing to another variable
    """
    return is_wrapped(typ) and typ.is_reference


def unwrap(typ):
    """
    Returns the actual type that is wrapped inside in a container type, ie a pointer in the stack or heap memory
    """
    while is_wrapped(typ):
        typ = typ.over
    return typ


def check_wrapper(typ):
    """
    Different from basic types like int, float, etc. which the VALUE is passed into a variable, when a variable
    use a contiguous block of memory like string, lists, structured type, etc., it's its ADDRESS that is
    passed to other variables references it. Both variables that own ou reference a value must be wrapped as
    like a pointer
    """
    if hasattr(typ, "must_be_wrapped") and typ.must_be_wrapped:
        typ = Wrapper(typ)
    return typ


def check_heap_ownership(typ):
    if is_wrapped(typ) and not is_reference(typ):
        typ.is_heap_owner = True
    return typ


def is_concrete(node, include_non_specialized=False):
    """
    Check that the function or type can be translated to IR code
    """

    # Return whether function is not a template or method from type template
    if hasattr(node, "get_all_type_vars"):
        type_vars = node.get_all_type_vars()
    elif hasattr(node, "type_vars"):
        type_vars = node.type_vars
    else:
        type_vars = None
    if type_vars is not None:
        for type_var in type_vars.values():
            if not is_concrete(type_var, include_non_specialized):
                return False

    # Unwrap the type if necessary
    if is_wrapped(node):
        return is_concrete(node.over, include_non_specialized)

    # If type is concrete but derived from something like 'anyint' or 'anyfloat', returns false
    if isinstance(node, ast.TypeVar) or (not include_non_specialized and node.is_non_specialized):
        return False

    return True


def get_formal_types(module, method, cls=None):
    """
    Prepare the list of types of the formal arguments accepted by the method
    """
    translations = {}
    if cls is not None:
        translations.update(cls.type_vars)
    translations.update(method.type_vars)
    is_concrete = True
    for type_name in translations:
        if isinstance(translations[type_name], ast.TypeVar):
            is_concrete = False
    if not is_concrete:
        formal_types = [module.instance_type(arg.type, translations=translations) for arg in method.args]
    else:
        formal_types = [arg.type for arg in method.args]
    return formal_types


def is_compatible(actual, formal, mode="default", accept_bigger_type=True):
    """
    Check that the list of actual types match the formal types' list.
    """
    numeric_types = INTEGERS | FLOATS

    # If both types are Concrete types then check compatibility of all elements of each one
    if hasattr(actual, "elements") and hasattr(formal, "elements"):
        pairs = zip(actual.elements, formal.elements)
        return all(is_compatible(i[0], i[1], mode) for i in pairs)

    # If both types are structured types like lists, iterables, tuples, etc, then check compatibility of all
    # elements of each one
    elif isinstance(actual, (tuple, list)) and isinstance(formal, (tuple, list)):
        if len(actual) != len(formal):
            return False
        elif formal and formal[-1] == VariadicArgs():
            return all(is_compatible(i[0], i[1], mode) for i in zip(actual, formal[:-1]))
        else:
            return all(is_compatible(i[0], i[1], mode) for i in zip(actual, formal))

    # Check individually if both types are compatible
    elif actual == formal:
        return True
    elif isinstance(actual, ast.TypeVar) and isinstance(formal, ast.TypeVar) and actual.name == formal.name:
        return True
    elif (isinstance(actual, ast.TypeVar) or isinstance(formal, ast.TypeVar)) and mode == "args":
        return True
    elif is_reference(actual) and not is_reference(formal):
        return False
    elif isinstance(actual, Function) and isinstance(formal, Function):
        return is_compatible(actual.over["ret"], formal.over["ret"], mode) and \
               is_compatible(actual.over["args"], formal.over["args"], mode)
    elif actual.name == "anytype":
        return True
    elif actual in numeric_types and formal in numeric_types:
        if util.AUTOMATIC_CASTING:
            if actual.name in ["anyint", "anyfloat"] or formal.name in ["anyint", "anyfloat"]:
                return True
            elif not accept_bigger_type:
                return actual.bits <= formal.bits
            else:
                return True
        elif actual != formal:
            if (actual.name == "anyint" and formal in INTEGERS) or \
               (formal.name == "anyint" and actual in INTEGERS) or \
               (actual.name == "anyfloat" and formal in FLOATS) or \
               (formal.name == "anyfloat" and actual in FLOATS):
                return True
            else:
                return False

    # Unwrap both types and check if they are compatible
    elif is_wrapped(actual) and is_wrapped(formal):
        return is_compatible(unwrap(actual), unwrap(formal), mode)
    elif (is_wrapped(actual) or is_wrapped(formal)) and mode == "args":
        return is_compatible(unwrap(actual), unwrap(formal), mode)

    elif isinstance(formal, Trait):

        # Check compatibility between methods of the both types
        for name, formal_methods in formal.methods.items():

            # If formal method's name doesn't even exist in the actual type's methods then both types are incompatible
            if name not in actual.methods:
                return False

            # Check if return types are the same
            actual_ret_type = actual.methods[name][0].type.over["ret"]
            formal_ret_type = formal_methods[0].type.over["ret"]
            if not is_compatible(actual_ret_type, formal_ret_type, mode):
                return False

            # Get the list of argument types for the formal type's methods
            formal_args_types = set()
            for fn in formal_methods:
                formal_args_types.add(tuple(at for at in fn.type.over["args"][1:]))

            # Get the list of argument types for the actual type's methods
            actual_args_types = set()
            for fn in actual.methods[name]:
                actual_args_types.add(tuple(at for at in fn.type.over["args"][1:]))

            # Check if the lists of argument types are compatible
            if formal_args_types != actual_args_types:
                return False

            return True

    return False


def select_method(module, node, cls, method_name, methods, positional, named, error_if_not_found=True):

    # Get all options of methods with the same name
    method_found = False
    options = []
    for method in methods:
        if method.name == method_name or (method_name == "__init__" and method.name == "__new__"):
            if method.name == method_name:
                method_found = True
            options.append(method)

    # Check if the method actually exists in this type
    if not method_found:
        if error_if_not_found:
            msg = (node.pos, "'{type}' does not have a method '{method}'".format(type=cls.name, method=method_name))
            hints = ["Check whether there is a typo in the name."]
            raise util.Error([msg], hints=hints)
        else:
            return None

    if len(named) > 0:
        assert False, named

    # Traverse all method options scoring with higher notes those where the types of the formal list fits better the
    # types of passed list of arguments
    scored, candidates = [], []
    for method in options:

        # Prepare the list of types of the actual arguments passed to the call
        actual_types = positional[1:]

        # Prepare the list of types of the formal arguments accepted by the method
        formal_types = get_formal_types(module, method, cls)
        if method.name != "__new__":
            formal_types = formal_types[1:]

        # Score the candidates comparing the types of the formal list with the argument list
        candidates.append((method.name, formal_types))
        if len(formal_types) == len(actual_types):

            # A method with no arguments always must be the first choice
            if len(formal_types) == 0:
                return method

            score = 0
            for actuals, formals in zip(actual_types, formal_types):
                if not is_compatible(actuals, formals, "args"):
                    score -= 1000
                    break
                elif actuals == formals:
                    score += 10
                else:
                    score += 1

            # Puts the current option as a potential method once it reached minimal score
            if score > 0:
                scored.append([method, score])

    if len(scored) > 0:

        # Choose the method which best fit the actual arguments
        scored.sort(key=lambda n: n[1])
        chosen_method = scored[0][0]
        return chosen_method

    elif error_if_not_found:

        # Raise an error if no method matched the signature
        msg = (node.pos, "no matching method found for the call's arguments")
        hint = "Methods tried for '({actual_types})' arguments:\n" \
            .format(actual_types=", ".join(typ.name for typ in actual_types))
        for name, formal_types in candidates:
            formal_type_names = ", ".join(typ.name for typ in formal_types)
            hint += ("        {name}({formal_types})\n".format(
                name=name,
                formal_types=formal_type_names))
        if len(candidates) > 0:
            hints = [hint]
        else:
            hints = None
        raise util.Error([msg], hints=hints)


def choose_bigger_type(left_type, right_type):
    """
    Choose between two types which is bigger based on its nature and number of bits. Examples:

        i16,   i32 -> i32    (i32 can store bigger numbers than those in i16)
        i32, float -> float  (float needs store precision)
        u16,   i16 -> i16    (signed integer needs store negative numbers)

    In expressions, choosing the biggest type is important, because if a float number is converted to an integer,
    for example, you will lose information such as accuracy. Whereas in the opposite, this does not happen.
    """
    numeric_types = INTEGERS | FLOATS

    def is_float(typ):
        return typ in FLOATS

    def is_integer(typ):
        return is_signed_integer(typ) or is_unsigned_integer(typ)

    def is_signed_integer(typ):
        return typ in SIGNED_INTEGERS

    def is_unsigned_integer(typ):
        return typ in UNSIGNED_INTEGERS

    # Do nothing if both types are equal
    if left_type == right_type:
        return left_type

    # Priorize floats in order to preserve decimal places
    elif is_float(left_type) or is_float(right_type):
        if is_integer(left_type):
            return right_type
        elif is_integer(right_type):
            return left_type
        elif left_type.name == "anyfloat":
            return right_type
        elif right_type.name == "anyfloat":
            return left_type

    # Priorize signed integers in order to preserve negative numbers
    elif is_signed_integer(left_type) or is_signed_integer(right_type):
        if is_unsigned_integer(left_type):
            return right_type
        elif is_unsigned_integer(right_type):
            return left_type
        elif left_type.name == "anyint":
            return right_type
        elif right_type.name == "anyint":
            return left_type

    # If types are both integers or both floats, but with different sizes, choose the one with the biggest size
    if left_type in numeric_types and right_type in numeric_types:
        left_num_bits, right_num_bits = BASIC[left_type.name]["num_bits"], BASIC[right_type.name]["num_bits"]
        if right_num_bits is None:
            return left_type
        elif left_num_bits is None:
            return right_type
        elif left_num_bits > right_num_bits:
            return left_type
        else:
            return right_type
    else:
        return left_type


def check_basic_type(typ):

    if typ.name in BASIC:
        typ.ir = BASIC[typ.name]["ir"]
        typ.byval = True
        typ.must_be_wrapped = False

        group, typ.signed, typ.bits = BASIC[typ.name]["group"], BASIC[typ.name]["signed"], BASIC[typ.name]["num_bits"]
        if group == "integer":
            # If node represents an integer type then add it to the lists of integer types which are used by
            # other modules
            INTEGERS.add(typ)
            if typ.signed:
                SIGNED_INTEGERS.add(typ)
            else:
                UNSIGNED_INTEGERS.add(typ)

        elif group == "floating":
            # If node represents a float type then add it to the lists of float types which are used by
            # other modules
            FLOATS.add(typ)


class ReprId(object):
    """
    The root base type for all types in ragaz.
    """
    byval = False
    must_be_wrapped = False

    def __hash__(self):
        return hash(repr(self))

    def __eq__(self, other):
        return repr(self) == repr(other)

    def __ne__(self, other):
        return not self.__eq__(other)

    def select(self, module, node, name, positional, named, error_if_not_found=True):
        """
        As that in a class there are methods with same name but with different signatures (formal parameters list) this
        function selects the proper method to the passed list of parameters.

        Example:
            class Foo():
                def bar(a: int) -> bool
                    ...
                def bar(a: float, b: int) -> bool
                    ...
        """

        # Ungroup the methods (with the same name) by creating a simplified list
        methods = []
        for grouped_methods in self.methods.values():
            methods += grouped_methods

        method = select_method(module, node, self, name, methods, positional, named, error_if_not_found)
        return method


class Base(ReprId):
    """
    The base type for most types except traits, templates and iterables.
    """
    is_mutable = False
    is_non_specialized = None
    attributes = {}
    methods = {}

    def __repr__(self):
        return "<type: {type}>".format(type=self.__class__.__name__)

    @property
    def name(self):
        return self.__class__.__name__


class Trait(ReprId):
    """
    In computer programming, a trait is a concept used in object-oriented programming, which represents a set of methods
    that a type must implement to extend the functionality of a class.

    trait Vehicle:
        def __str__(self) -> str

    class Motorcycle(Vehicle):
        def __str__(self) -> str:
            (some stuff)

    class Car(Vehicle):
        def __str__(self) -> str
            (some stuff)

    def print_vehicle(v: Vehicle):
        print(v)

    some_car = Car()
    print_vehicle(some_car)

    In the above example, both `Motorcycle` and `Car` classes implement the `Vehicle` trait. However, each one will
    implement the `__str__` method in different ways. Because this, the argument type in the `print_vehicle` function
    is just the `Vehicle` trait; without it we would have to create one `print` function for every type.
    """
    is_non_specialized = None
    attributes = {}
    methods = {}

    def __repr__(self):
        return "<trait: {trait}>".format(trait=self.name)

    @property
    def name(self):
        return self.__class__.__name__


class Template(ReprId):
    """
    This is type is used as base for Generics. As in other languages, a template allows you reuse the same
    code for different types only replacing the famous T to the specific type.
    """
    attributes = {}
    methods = {}

    def __repr__(self):
        return "<template: {template}>".format(template=self.__class__.__name__)

    @property
    def name(self):
        return self.__class__.__name__


class Wrapper(Base):
    """
    Type used for typing objects which are allocated in stack/heap memory
    """

    def __init__(self, over, is_mutable=False, is_heap_owner=False, is_reference=False):
        self.over = over
        self.is_heap_owner = is_heap_owner
        self.is_reference = is_reference
        self.is_mutable = is_mutable

    def __repr__(self):
        if self.is_reference:
            prefix = "ref_ptr"
        elif self.is_heap_owner:
            prefix = "owner_ptr"
        else:
            prefix = "ptr"
        return "<type: {prefix}<{type}>>".format(prefix=prefix,
                                               type=self.over.name)

    @property
    def name(self):
        if self.is_reference:
            prefix = "&"
        else:
            prefix = ""
        return "{mut}{prefix}{type}".format(mut="~" if self.is_mutable else "",
                                            prefix=prefix,
                                            type=self.over.name)

    @property
    def ir(self):
        return self.over.ir.as_pointer()


class Data(Base):
    """
    Type used for typing contiguous data which are allocated in heap memory
    """
    is_heap_owner = True

    def __init__(self, over):
        self.over = over

    def __repr__(self):
        return "<type: data<{type}>>".format(type=self.over.name)

    @property
    def name(self):
        return "data<{type}>".format(type=self.over.name)

    @property
    def ir(self):
        return self.over.ir.as_pointer()


class VariadicArgs(Base):
    """
    The purpose of the class is only simulate a compatible type for c/c++ variadic functions (ie. functions which take
    a variable number of arguments like `printf`). When you import an external function which will be linked to a static
    library you must declare it and then use it in the module, but you must keep the exact signature:

        def snprintf(str: &byte, size: i32, format: &byte, *args) -> i32

    In the above example, the `*args` is equivalent to `...` in C/C++
    """
    pass


class Function(Base):
    """
    The purpose of the class is give support to a variable store a function reference as its value.

    Example:
        def foo(a: int, b: int) -> bool
            return a < b

        bar: def(int, int) -> bool  # Define the type of `bar` as function specifying its return and arguments types.
        bar = foo  # Assigns `foo` reference to `bar`
        bar(1, 2)  # call `bar` which will print `True`
    """

    def __init__(self, ret_type, args_types, is_extern_c=False):
        self.over = {"ret": ret_type, "args": args_types}
        self.is_extern_c = is_extern_c

    def __repr__(self):
        args_types = ["{type!r}".format(type=i) for i in self.over["args"]]
        ret_type = self.over["ret"]
        return "<fn {ret_type!r} <- [{args_types}]>".format(ret_type=ret_type, args_types=", ".join(args_types))

    @property
    def name(self):
        args_types = [arg.name for arg in self.over["args"]]
        ret_type = self.over["ret"].name
        return "function({args_types}) -> {ret_type}".format(args_types=", ".join(args_types), ret_type=ret_type)

    @property
    def ir(self):
        ret_type, formal_types = self.over["ret"], self.over["args"]
        args_types = []
        var_arg = False
        for arg_type in formal_types:
            if isinstance(arg_type, VariadicArgs):
                var_arg = True
            else:
                args_types.append(arg_type.ir)
        return ir.FunctionType(ret_type.ir, args_types, var_arg=var_arg).as_pointer()


def create_type_or_trait(node, name, internal_name, type_vars={}):
    """
    Create a type or trait based on node's info.
    """

    fields = {
        "name": name,
        "methods": {},
        "must_be_wrapped": True,
        "type_vars": type_vars}
    if len(type_vars) > 0:
        fields["elements"] = list(type_vars.values())

    if isinstance(node, ast.Trait):
        parent = Trait
    else:
        parent = Base
        fields["attributes"] = {}

    typ = type(internal_name, (parent,), fields)()

    # Add the type attributes based on node's info
    if isinstance(node, ast.Class):

        # Create the 'id' attribute for types passed by reference
        if typ.name not in BASIC and typ.name not in ["UnwEx", "Exception"]:
            typ.attributes["id"] = {"idx": 0, "type": ast.Type(None, "uint")}
            start = 1
        else:
            start = 0

        for i, (attribute_type, name) in enumerate(node.attributes, start=start):
            ignore = False

            # If type is a tuple then  ignore all attributes for capacity greater the current number of elements
            if typ.name.startswith("tuple<") and name.name.startswith("element_"):
                suffix = int(name.name.split("_")[-1])
                if suffix >= len(typ.elements):
                    ignore = True

            if not ignore:
                typ.attributes[name.name] = {"idx": i, "type": attribute_type}

    # Add the type methods based on node's info
    for i, method in enumerate(node.methods):
        ignore = False

        # If type is a tuple then  ignore all methods for capacity greater the current number of elements
        if typ.name.startswith("tuple<") and (method.name.startswith("eq_") or method.name.startswith("str_")):
            splitted_name = method.name.split("_")
            preffix = splitted_name[0]
            suffix = int(splitted_name[-1])
            if suffix > len(typ.elements):
                ignore = True
            elif suffix == len(typ.elements):
                method.name = "last_{name}".format(name=preffix)

        if not ignore:
            if isinstance(node, ast.Trait) and method.name in typ.methods:
                msg = (typ.methods[method.name][0].pos, "method was declared with the name '{name}'".format(name=method.name))
                msg2 = (method.pos, "but this method also was declared with the same name")
                raise util.Error([msg, msg2])

            method.idx = i
            method.self_type = typ
            typ.methods.setdefault(method.name, []).append(method)

    return typ


def finalize_function_or_method(module, node, type_vars={}):
    """
    Update the function node with more info and create a function type to serve as type to functions or variables.
    """

    node.type_vars = type_vars

    # Set the module to translate types based on these 'type_vars'
    translations = {}
    translations.update(node.get_all_type_vars())
    if node.self_type is not None:
        translations["Self"] = node.self_type

    # Process the function's arguments
    args = OrderedDict()
    for arg in node.args:
        if arg.name == "self":
            # Set 'self's type as the class type itself
            if arg.type is None:
                arg.type = node.self_type
                arg.type = Wrapper(arg.type)
                if node.name == "__del__":
                    arg.type.is_heap_owner = True
                else:
                    arg.type.is_reference = True
            else:
                msg = (node.args[0].type.pos, "'self' argument cannot have an explicit type")
                hints = ["Remove ': {type}'.".format(type=node.args[0].type.name)]
                raise util.Error([msg], hints=hints)
        elif arg.type is not None:
            arg.type = module.instance_type(arg.type, translations=translations)
            arg.type = check_wrapper(arg.type)
            arg.type = check_heap_ownership(arg.type)
        else:
            msg = (arg.pos, "no type was specified to '{arg}'".format(arg=arg.name))
            hints = ["Define the argument using the ': sometype' syntax."]
            raise util.Error([msg], hints=hints)

        args[arg.name] = arg.type

    # Set the type object for the return type
    if node.ret is None:
        ret_type = module.instance_type("void")
    elif node.name not in VOID_FUNCTIONS:
        ret_type = module.instance_type(node.ret, translations=translations)
    else:
        # Some methods must have return type "void"
        msg = (node.ret.pos, "method '{fn_name}' must return no value".format(fn_name=node.name))
        hints = ["How about remove '-> {ret_type}'?".format(ret_type=node.ret.name)]
        raise util.Error([msg], hints=hints)
    ret_type = check_wrapper(ret_type)
    ret_type = check_heap_ownership(ret_type)

    # Create unique name for the derived method
    if node.suite is None or node.name == "main":
        # Name must be the original because it's a declaration as there are no statements (suite is empty)
        node.internal_name = node.name
    else:
        if len(type_vars) > 0:
            node.name = "{name}<{derivation_types}>".\
                format(name=node.name, derivation_types=", ".join("{type}".format(type=tp.name)
                                                                  for tp in type_vars.values()))
        if node.self_type is not None:
            node.internal_name = "{module}.{type}.{name}".format(module=module.name, type=node.self_type.name,
                                                                 name=node.name)
        else:
            node.internal_name = "{module}.{name}".format(module=module.name, name=node.name)
        node.internal_name += "(" + (", ".join(typ.type.name for typ in node.args)) + ")"

    # Process the function's type
    typ = Function(ret_type, list(args.values()), is_extern_c=node.is_extern_c)

    return typ


def finalize_type_or_trait(module, typ):
    """
    Finish the pending tasks for build types for classes
    """

    # Set the module to translate types based on these 'type_vars'
    translations = {}
    translations.update(typ.type_vars)
    translations["Self"] = typ

    # Set the type of the attributes
    if isinstance(typ, Base):
        for name, attribute in typ.attributes.items():
            if attribute["type"] is not None:
                attribute["type"] = check_wrapper(module.instance_type(attribute["type"], translations=translations))

    # Set the type of the methods
    for name in typ.methods:
        for method in typ.methods[name]:

            # Set the method with the proper type
            if len(method.type_vars) == 0:
                method.type = finalize_function_or_method(module, method)


def extract_type_vars(module, infer_types, formals, actuals, wanted_types):
    """
    When the actual types were explicitly passed, we need just associate them with template's formal type_vars
    However when actual types weren't passed, we must infer from call
    """

    if infer_types:
        # Example of inference:
        #
        # def foo<T, T2>(a: T, b: T2):
        #     pass
        #
        # foo(1 as i32, 2.5 as float)
        #
        # In the example above, 'T' becomes 'i32' and 'T2' becomes 'float'

        def infer(formal, actual):
            if is_wrapped(formal) and is_wrapped(actual):
                infer(unwrap(formal), unwrap(actual))
            elif hasattr(formal, "elements") and hasattr(actual, "elements"):
                for i, _ in enumerate(formal.elements):
                    infer(formal.elements[i], actual.elements[i])
            elif isinstance(formal, Data) and isinstance(actual, Data):
                infer(formal.over, actual.over)
            elif isinstance(formal, Function) and isinstance(actual, Function):
                infer(formal.over["ret"], actual.over["ret"])
                for formal, actual in zip(formal.over["args"], actual.over["args"]):
                    infer(formal, actual)
            elif formal.name in wanted_types:
                type_vars[formal.name] = actual

        type_vars = {}
        formals = [unwrap(formal) for formal in formals[:len(actuals)]]
        for i, formal in enumerate(formals):
            infer(formal, actuals[i])

    else:
        # Example of straightforward extraction:
        #
        # def foo<T, T2>(a: T, b: T2):
        #     pass
        #
        # foo.<i32, float>(1, 2.5)
        #
        # In the example above, 'T' also becomes 'i32' and 'T2' becomes 'float'. But in this case, we explicitly
        # pass the actual types between braces before pass the arguments
        type_vars = {formal: derivation for (formal, derivation) in zip(wanted_types, actuals)}

    return type_vars


def get_derived_type(module, template, infer_types, derivation_types, init_fn=None, is_method_as_generator=False):

    # When the actual types were explicitly passed, we need just associate them with class's formal type_vars
    # However when actual types weren't passed, we must infer from '__init__' call
    if infer_types:
        formal_types = [formal for formal in get_formal_types(module, init_fn, template)[1:]]
        if is_method_as_generator:
            formal_types = [ast.TypeVar(None, name) for name in template.type_vars.keys()] + formal_types
    else:
        formal_types = None
    type_vars = extract_type_vars(module, infer_types, formal_types, derivation_types, template.type_vars.keys())

    name = "{name}<{derivation_types}>".format(name=template.name,
                                               derivation_types=", ".join("{type}".format(type=tp.name)
                                                                          for tp in type_vars.values()))

    # Create the derived type if it doesn't exist
    typ = module.types.get(name, None)
    if typ is None:

        # Create a structured type based on template's info
        node = copy.deepcopy(template)
        typ = create_type_or_trait(node, name, name, type_vars)
        finalize_type_or_trait(module, typ)

        if not isinstance(typ, Trait):
            for method_name in typ.methods:
                module.functions.extend(typ.methods[method_name])
        module.types[name] = typ

    return typ


def get_constructor(module, call_node, cls, infer_types, derivation_types, positional, named, is_method_as_generator=None):

    # If it's NOT a template class, just use the callable object instance
    if len(cls.type_vars) == 0:
        self_type = unwrap(module.types[cls.name])

    # If it's a template class, use the derived type from it with the actual types
    else:

        # Create a type for this derivation from template
        # After this, set the new '__init__[T]' to be the method to be called
        if infer_types:
            method = select_method(module, call_node, cls, "__init__", cls.methods,
                                   positional, named)
        else:
            method = None
        self_type = get_derived_type(module, cls, infer_types, derivation_types, init_fn=method,
                                     is_method_as_generator=is_method_as_generator)

    fn = self_type.select(module, call_node, "__init__", positional, named)
    return fn


def get_function(module, callable_object, infer_types, derivation_types, positional=None, named=None, self_type=None):

    # If it's NOT a template function, just return the callable object
    if len(callable_object.type_vars) == 0:
        fn = callable_object

    # If it's a template function, create a derived function from it with the actual types
    else:

        # When the actual types were explicitly passed, we need just associate them with template's formal type_vars
        # However when actual types weren't passed, we must infer from call
        if infer_types:
            formal_types = get_formal_types(module, callable_object, self_type)
            if self_type is not None:
                formal_types = formal_types[1:]
        else:
            formal_types = None
        type_vars = extract_type_vars(module, infer_types, formal_types, derivation_types, callable_object.type_vars.keys())
        if self_type is not None:
            type_vars.update(self_type.type_vars)

        internal_name = "{name}<{derivation_types}>".format(name=callable_object.name,
                                                            derivation_types=", ".join("{type}".format(type=tp.name)
                                                                                       for tp in type_vars.values()))

        # Create the derived function if it doesn't exist
        if self_type is not None:
            fn = self_type.select(module, callable_object, internal_name, positional, named, error_if_not_found=False)
        else:
            fn = module.symbols.get(internal_name, None)
        if fn is None:

            # Create a function based on template's info
            fn = copy.deepcopy(callable_object)
            fn.self_type = self_type
            fn.type = finalize_function_or_method(module, fn, type_vars)

            if self_type is not None:
                self_type.methods.setdefault(internal_name, []).append(fn)
            else:
                module.symbols[internal_name] = fn
            if not isinstance(self_type, Trait):
                module.functions.append(fn)

    return fn
