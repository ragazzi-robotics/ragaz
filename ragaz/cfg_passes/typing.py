"""
This pass infers the type and check compatibility of the types in a context.

Before all, it first traverses all classes stored in symbols table and create 'Python types' from them (using
the builtin 'type()' function). The pythonic type contains data like name, attributes and methods of a Ragaz
type (which allows check a type using the famous 'isinstance', for instance). Then, once a class types are created
we can recover them using a module's function called 'instance_type()' which return an already created type through a
string containing its name, for instance. This same function also can create a type from a template class when
a string like 'list<int>' is passed to it: it creates a derived type named 'list<int>' from a template
named 'list<T>' (see '__builtins__' module) which is specific for integer types.

Once the types are created we can walk over the CFG (control-flow graph) of a function to typing nodes, checking if the
types are compatible for a context (like a return value or an element in binary operation), etc., using functions
like 'types.is_compatible()', the pythonic 'isinstance', or directly comparing using the '==' operator.

In some cases, the type for node is not definitive. An example, is those typed with 'anyint' or 'anyfloat'. They
will receive a definitive type like 'int', 'f32', etc., in the 'specialization' pass which will analyse the context
and check the best type the fit it.
"""

import copy
from ragaz import types_ as types, ast_ as ast, module as module_, util
from ragaz.ast_passes import flow

PASS_NAME = __name__.split(".")[-1]


def organize_args(args):
    positional, named, last_named_arg = [], {}, None
    for arg in args:
        if isinstance(arg, ast.NamedArg):
            named[arg.name] = arg.value.type
            last_named_arg = arg.name
        elif len(named) > 0:
            msg = (arg.pos, "non-named arguments must come before named arguments")
            hints = ["Move this value to front of '{named_arg}'.".format(named_arg=last_named_arg)]
            raise util.Error([msg], hints=hints)
        else:
            positional.append(arg.type)
    return positional, named


class Typer(object):

    def __init__(self, module):
        self.module = module
        self.fn = None
        self.definitions = None

    def process(self):

        # First collect all types (basic ones like integer or string, or structured ones like classes, tuples, etc)
        # visible only in the module.
        # Then check and/or infer the type of all global variables, functions, variables, etc, and set them with
        # correct type when appropriate.

        # Reset the set of functions to be processed by CFG passes
        self.module.functions = []

        # Create the 'int', 'uint', and 'float' types from existent types with the (word) size of the target
        # architecture
        if self.module.is_core:
            def copy_type(dst_type, src_type):
                self.module.symbols[dst_type] = node = copy.deepcopy(self.module.symbols[src_type])
                node.name = dst_type

            copy_type("int", "i" + str(types.WORD_SIZE))
            copy_type("uint", "u" + str(types.WORD_SIZE))
            copy_type("float", "f64")

        # Add type aliases
        for name, node in self.module.symbols.current_itens.items():
            if isinstance(node, module_.TypeAlias):
                self.module.types[name] = node

        # Add basics, classes and traits type to module's types dictionary
        for name, node in self.module.symbols.current_itens.items():
            if isinstance(node, (ast.Class, ast.Trait)) and len(node.type_vars) == 0:
                self.module.types[name] = typ = types.create_type_or_trait(node, node.name, node.name)
                types.check_basic_type(typ)

        # Finalize classes and traits types
        for name, node in self.module.symbols.current_itens.items():
            if isinstance(node, (ast.Class, ast.Trait)) and len(node.type_vars) == 0:
                typ = self.module.types[node.name]
                types.finalize_type_or_trait(self.module, typ)

                if not isinstance(typ, types.Trait):
                    for name in typ.methods:
                        methods = typ.methods[name]
                        self.module.functions.extend(methods)

        # Set the type object for all functions except class methods
        for name, node in self.module.symbols.current_itens.items():
            if isinstance(node, ast.Function) and len(node.type_vars) == 0:

                # Set the functions with the proper type
                node.type = types.finalize_function_or_method(self.module, node)

                if node.suite is not None:
                    self.module.functions.append(node)

                # Check function signature invariants for main() and methods
                if name == "main":
                    fn_types = self.module.symbols[node.name].type.over
                    ret_type, args_types = fn_types["ret"], fn_types["args"]
                    # TODO: Implement sys.argv with this:
                    if len(node.args) > 0:
                        if args_types[0].name != "list<str>":
                            msg = (node.args[0].pos, "first and single argument to 'main()' must be of type 'list<str>'"
                                                     " ('{type}' not allowed)".format(type=args_types[0].name))
                            raise util.Error([msg])
                    if ret_type not in {self.module.instance_type("void"), self.module.instance_type("i32")}:
                        msg = (node.ret.pos, "'main()' must return either nothing or 'i32' ('{type}' not allowed)"
                               .format(type=ret_type.name))
                        raise util.Error([msg])

        # Set the type object for the global variables
        for name, node in self.module.symbols.current_itens.items():
            if isinstance(node, module_.Global):

                # Infer the global variable's type from its value
                if node.value.type is None:
                    if isinstance(node.value, ast.Bool):
                        node.value.type = self.module.instance_type("bool")
                    elif isinstance(node.value, ast.Byte):
                        node.value.type = self.module.instance_type("byte")
                    elif isinstance(node.value, ast.Int):
                        node.value.type = self.module.instance_type("int")
                    elif isinstance(node.value, ast.Float):
                        node.value.type = self.module.instance_type("float")
                    elif isinstance(node.value, ast.String):
                        node.value.type = self.module.instance_type("str")
                else:
                    node.value.type = self.module.instance_type(node.value.type)
                node.type = node.value.type

                # Round the values if necessary
                if node.value.type in types.FLOATS:
                    node.value.literal = float(node.value.literal)
                elif node.value.type in types.INTEGERS:
                    node.value.literal = int(node.value.literal)

        # Use methods of default integer/float for 'anyint'/'anyfloat' (numbers with no size defined yet)
        self.module.instance_type("anyint").methods.update(self.module.instance_type("int").methods)
        self.module.instance_type("anyfloat").methods.update(self.module.instance_type("float").methods)

        # Visit the actual function code for type checking and inference of its statements
        # (needs to be done after add function declarations for each function)
        for fn in self.module.functions:
            self.visit_function(fn)

    # Some type system helper methods

    def check_mutable(self, pos, val):
        """
        This method is used to raise an error if name's value is being modified but its type is immutable.
        """
        if util.MUTABILITY_CHECKING and not self.module.is_core:  # TODO: Remove CORE verification, because this check needs be done on it too
            if self.fn.name not in ["__init__", "__new__"] and types.is_wrapped(val.type) and not val.type.is_mutable:
                if isinstance(val, ast.Symbol):
                    obj = self.definitions[val.get_name()]
                else:
                    obj = self.definitions[val.obj.get_name()]
                msg = (obj.pos, "object defined as not mutable")
                msg2 = (pos, "but changed here".format(type=val.type.name))
                hints = ["Consider make it mutable putting the '~' operator in front its type."]
                raise util.Error([msg, msg2], hints=hints)

    def define_variable(self, var):
        if var.get_name() not in self.definitions:
            self.definitions[var.get_name()] = var

    def symbol_is_type(self, symbol):
        return symbol.name == "data" or symbol.name in self.module.types

    def check_symbol_definition(self, node, types_not_allowed=True):
        symbol = None

        # Check if symbol is a local variable, and if yes, return the local variable
        var = self.definitions.get(node.get_name(), None)
        if var is not None:
            symbol = var

        # If symbol wasn't defined locally in any block of the function then check if is a global type and return it
        elif node.name in self.module.types:
            symbol = self.module.types[node.name]
            if types_not_allowed:
                msg = (node.pos, "object is a type, not a value")
                raise util.Error([msg])

        # If symbol wasn't defined locally in any block of the function then check if is a global variable,
        # function, etc., and return it
        elif node.name in self.module.symbols:
            symbol = self.module.symbols[node.name]

            # If it's a type, raises an error
            if isinstance(symbol, ast.Class) and types_not_allowed:
                msg = (node.pos, "object is a type, not a value")
                raise util.Error([msg])

            # Create a concrete function or type from template object (class, method or function) and the actual types
            elif isinstance(symbol, ast.Function) and node.derivation_types is not None:
                node.derivation_types = [self.module.instance_type(typ, translations=self.translations)
                                         for typ in node.derivation_types]
                fn = types.get_function(self.module, symbol, False, node.derivation_types)
                symbol.type = fn.type
                node.name = fn.name

        # Raises an error if no symbol was found
        if symbol is not None:
            return symbol
        else:
            msg = (node.pos, "object is not defined")
            hints = ["Check whether there is a typo in the name.",
                     "If you already declared it, check whether it is in this scope."]
            raise util.Error([msg], hints=hints)

    def visit(self, node):
        """
        This is used for call the proper visit method for a node. If node, for instance, is an ast.String, then
        this method will call `visit_string` method to handle the node properly.
        """
        fn_name = "visit_" + str(node.__class__.__name__).lower()
        visit_node_fn = getattr(self, fn_name)
        visit_node_fn(node)

    # Node visitation methods

    def visit_function(self, fn):
        """
        Start the analysis.
        """
        util.check_previous_pass(self.module, fn, PASS_NAME)
        if PASS_NAME not in fn.passes and types.is_concrete(fn, True):
            self.fn = fn
            self.definitions = util.ScopesDict()

            # Set the module to translate types based on these 'type_vars'
            translations = {}
            translations.update(fn.get_all_type_vars())
            if fn.self_type is not None:
                translations["Self"] = fn.self_type
            self.translations = translations

            # Add arguments to function's scope
            for arg in fn.args:
                self.define_variable(arg)

            # Visit the function blocks to typing its arguments and internal variables
            for block in sorted(self.fn.flow.blocks, key=lambda blk: blk.id):
                for step in sorted(block.steps, key=lambda stp: stp.id):
                    self.visit(step)

        self.fn.passes.append(PASS_NAME)

    def visit_beginscope(self, node):

        # Create a scope object for variable definitions; this is crucial for find a local variable's name in
        # the scopes of a function
        self.definitions = util.ScopesDict(self.definitions)

        return node

    def visit_endscope(self, node):
        self.definitions = self.definitions.parent
        return node

    # Basic types

    def visit_noneval(self, node):
        node.type = self.module.instance_type("anytype")

    def visit_bool(self, node):
        node.type = self.module.instance_type("bool")

    def visit_int(self, node):
        # First set a temporary and generic integer type. Only after `specialize` pass it will get a definitive type
        # like i8, 32, etc.
        node.type = self.module.instance_type("anyint")

    def visit_float(self, node):
        # First set a temporary and generic float type. Only after `specialize` pass it will get a definitive type
        # like i8, 32, etc.
        node.type = self.module.instance_type("anyfloat")

    def visit_byte(self, node):
        node.type = self.module.instance_type("byte")

    # Structures

    def visit_array(self, node):
        self.visit(node.num_elements)
        node.target_type = self.module.instance_type(node.target_type, translations=self.translations)
        node.type = types.Wrapper(self.module.instance_type(
            ast.DerivedType(None, "array", [node.target_type]), translations=self.translations))

    def visit_string(self, node):
        # All strings should be set to str
        node.type = types.Wrapper(self.module.instance_type("str"))

    def visit_tuple(self, node):
        if len(node.elements) > types.MAX_TUPLE_ELEMENTS:
            msg = (node.pos, "a tuple can have a maximum of {max_elements} elements (this one has {num_elements})"
                   .format(max_elements=types.MAX_TUPLE_ELEMENTS, num_elements=len(node.elements)))
            raise util.Error([msg])

        for element in node.elements:
            self.visit(element)
        node.type = types.Wrapper(self.module.instance_type(
            ast.DerivedType(None, "tuple", [types.unwrap(element.type) for element in node.elements]), translations=self.translations))

    def get_biggest_element_type(self, elements):

        # Once the all elements of the collection must have the same type then try find which is the biggest elements'
        # type of the list checking if all elements are compatible
        biggest_element_type = None
        if len(elements) > 0:
            for element in elements:
                self.visit(element)

                # Set an initial value for element's type
                if biggest_element_type is None:
                    biggest_element_type = element.type

                if not types.is_compatible(element.type, biggest_element_type):
                    msg = (element.pos, "elements have mismatch types ('{type1}' vs '{type2}')"
                           .format(type1=biggest_element_type.name, type2=element.type.name))
                    hints = ["Use 'as' keyword to convert values.",
                             "Create a magic method to convert implicitly the values."]
                    raise util.Error([msg], hints=hints)
                else:
                    biggest_element_type = types.choose_bigger_type(biggest_element_type, element.type)
        else:
            biggest_element_type = self.module.instance_type("anytype")

        return types.unwrap(biggest_element_type)

    def visit_list(self, node):

        # Set the type of list with the biggest type found
        node.type = types.Wrapper(self.module.instance_type(
            ast.DerivedType(None, "list", [self.get_biggest_element_type(node.elements)]), translations=self.translations))

    def visit_dict(self, node):

        # Set the type of dict with the biggest type found for keys and values
        key_type = self.get_biggest_element_type(node.elements.keys())
        value_type = self.get_biggest_element_type(node.elements.values())
        node.type = types.Wrapper(self.module.instance_type(
            ast.DerivedType(None, "dict", [key_type, value_type]), translations=self.translations))

    def visit_set(self, node):

        # Set the type of set with the biggest type found
        node.type = types.Wrapper(self.module.instance_type(
            ast.DerivedType(None, "set", [self.get_biggest_element_type(node.elements)]), translations=self.translations))

    def visit_attribute(self, node):
        self.visit(node.obj)

        # Get the class type which attribute makes part
        obj_type = types.unwrap(node.obj.type)

        # Set the type to that of the attribute in the class
        if node.attribute in obj_type.attributes:
            node.type = obj_type.attributes[node.attribute]["type"]
        elif node.attribute in obj_type.methods:
            msg = (node.pos, "object is a method, not a value")
            raise util.Error([msg])
        else:
            msg = (node.pos, "attribute '{attribute}' was not found".format(attribute=node.attribute))
            hints = ["Check whether there is a typo in the name."]
            raise util.Error([msg], hints=hints)

    def visit_setattribute(self, node):
        self.visit_attribute(node)
        self.check_mutable(node.pos, node.obj)

    def visit_element(self, node, check_set_item=False):
        self.visit(node.key)
        self.visit(node.obj)

        if node.key.type not in types.INTEGERS:
            msg = (node.key.pos, "element index must be a integer type ('{type}' not allowed)"
                   .format(type=node.key.type.name))
            hints = ["Use 'as' keyword to convert values.",
                     "Create a magic method to convert implicitly the values."]
            raise util.Error([msg], hints=hints)

        # Get the collection type which element makes part
        obj_type = types.unwrap(node.obj.type)

        # Set the type of the element
        if obj_type.name.startswith("data<"):
            node.type = types.unwrap(node.obj.type.over)
            node.type = types.check_wrapper(node.type)

        elif obj_type.name.startswith("tuple<"):
            if not node.key.is_literal:
                msg = (node.key.pos, "element index must be a literal integer less or equal to '{num_elements}'"
                       .format(num_elements=len(obj_type.elements)-1))
                raise util.Error([msg])
            node.type = obj_type.attributes["element_" + str(node.key.literal)]["type"]

        else:

            if "__getitem__" in obj_type.methods:
                call_fn = obj_type.methods["__getitem__"][0]
                node.type = call_fn.type.over["ret"]
            elif check_set_item and "__setitem__" not in obj_type.methods:
                msg = (node.pos, "object has no method '__setitem__'")
                hints = ["Are you sure that this object is a collection (like list, tuple, etc.)?",
                         "Implement a magic method '__setitem__' in '{type}'.".format(type=obj_type.name)]
                raise util.Error([msg], hints=hints)
            else:
                msg = (node.pos, "object is not subscriptable")
                hints = ["Are you sure that this object is a collection (like list, tuple, etc.)?",
                         "Implement a magic method '__getitem__' in '{type}'.".format(type=obj_type.name)]
                raise util.Error([msg], hints=hints)

    def visit_setelement(self, node):
        self.visit_element(node, check_set_item=True)
        self.check_mutable(node.pos, node.obj)

    # Boolean operators

    def visit_not(self, node):
        self.visit(node.value)
        node.type = self.module.instance_type("bool")

    def boolean(self, node):
        self.visit(node.left)
        self.visit(node.right)
        if node.left.type == node.right.type:
            node.type = node.left.type
        else:
            node.type = self.module.instance_type("bool")

    def visit_and(self, node):
        self.boolean(node)

    def visit_or(self, node):
        self.boolean(node)

    # Comparison operators

    def visit_is(self, node):
        self.visit(node.left)
        self.visit(node.right)
        node.type = self.module.instance_type("bool")

    def compare(self, node):
        self.visit(node.left)
        self.visit(node.right)

        left_type, right_type = types.unwrap(node.left.type), types.unwrap(node.right.type)
        if types.is_compatible(right_type, left_type):
            node.type = self.module.instance_type("bool")
        else:
            msg = (node.pos, "logical operation '{op}' with types '{left_type}' and '{right_type}' cannot be performed"
                   .format(op=node.op, left_type=node.left.type.name, right_type=node.right.type.name))
            hints = ["Use 'as' keyword to convert values.",
                     "Create a magic method to convert implicitly the values."]
            raise util.Error([msg], hints=hints)

    def visit_equal(self, node):
        self.compare(node)

    def visit_notequal(self, node):
        self.compare(node)

    def visit_lowerthan(self, node):
        self.compare(node)

    def visit_lowerequal(self, node):
        self.compare(node)

    def visit_greaterthan(self, node):
        self.compare(node)

    def visit_greaterequal(self, node):
        self.compare(node)

    # Arithmetic operators

    def arith(self, node):
        self.visit(node.left)
        self.visit(node.right)

        left_type, right_type = types.unwrap(node.left.type), types.unwrap(node.right.type)
        if types.is_compatible(right_type, left_type):
            numeric_types = types.INTEGERS | types.FLOATS
            if left_type in numeric_types and right_type in numeric_types and util.AUTOMATIC_CASTING:
                node.type = types.choose_bigger_type(left_type, right_type)
            else:
                node.type = node.left.type
        else:
            msg = (node.pos, "arithmetic operation '{op}' with types '{left_type}' and '{right_type}' cannot "
                             "be performed".format(op=node.op, left_type=node.left.type.name,
                                                   right_type=node.right.type.name))
            hints = ["Use 'as' keyword to convert values.",
                     "Create a magic method to convert implicitly the values."]
            raise util.Error([msg], hints=hints)

    def visit_neg(self, node):
        self.visit(node.value)

        numeric_types = types.INTEGERS | types.FLOATS
        if node.value.type in numeric_types:
            node.type = node.value.type
        else:
            msg = (node.pos, "arithmetic operation '{op}' with type '{type}' cannot be performed"
                   .format(op=node.op, type=node.value.type.name))
            hints = ["Use 'as' keyword to convert values.",
                     "Create a magic method to convert implicitly the values."]
            raise util.Error([msg], hints=hints)

    def visit_add(self, node):
        self.arith(node)

    def visit_sub(self, node):
        self.arith(node)

    def visit_mul(self, node):
        self.arith(node)

    def visit_div(self, node):
        self.arith(node)

    def visit_mod(self, node):
        self.arith(node)

    def visit_floordiv(self, node):
        self.arith(node)

    def visit_pow(self, node):
        self.arith(node)

    # Bitwise operators

    def bitwise(self, node):
        self.visit(node.left)
        self.visit(node.right)

        left_type, right_type = types.unwrap(node.left.type), types.unwrap(node.right.type)
        if left_type in types.INTEGERS and right_type in types.INTEGERS:
            if util.AUTOMATIC_CASTING:
                node.type = types.choose_bigger_type(left_type, right_type)
            else:
                node.type = left_type
        else:
            msg = (node.pos, "bitwise operation '{op}' with types '{left_type}' and '{right_type}' cannot be performed"
                   .format(op=node.op, left_type=left_type.name, right_type=right_type.name))
            hints = ["This operation can be performed only with integers.",
                     "Use 'as' keyword to convert values.",
                     "Create a magic method to convert implicitly the values."]
            raise util.Error([msg], hints=hints)

    def visit_bwnot(self, node):
        self.visit(node.value)

        if node.value.type in types.INTEGERS:
            node.type = node.value.type
        else:
            msg = (node.pos, "bitwise operation '{op}' with type '{type}' cannot be performed"
                   .format(op=node.op, type=node.value.type.name))
            hints = ["Use 'as' keyword to convert values.",
                     "Create a magic method to convert implicitly the values."]
            raise util.Error([msg], hints=hints)

    def visit_bwand(self, node):
        self.bitwise(node)

    def visit_bwor(self, node):
        self.bitwise(node)

    def visit_bwxor(self, node):
        self.bitwise(node)

    def visit_bwshiftleft(self, node):
        self.bitwise(node)

    def visit_bwshiftright(self, node):
        self.bitwise(node)

    # Control flow

    def visit_pass(self, node):
        pass

    def visit_branch(self, node):
        return

    def visit_condbranch(self, node):
        self.visit(node.cond)

    def visit_phi(self, node):
        left = node.left[1]
        right = node.right[1]

        self.visit(left)
        self.visit(right)

        # Set the type of the name
        if left.type == right.type:
            node.type = left.type
        else:
            # When left or right value has no type set to it, take the other side's type
            if isinstance(left, ast.NoneVal):
                node.type = left.type = right.type
            elif isinstance(right, ast.NoneVal):
                node.type = right.type = left.type
            else:
                left_type, right_type = types.unwrap(left.type), types.unwrap(right.type)
                if types.is_compatible(right_type, left_type):
                    numeric_types = types.INTEGERS | types.FLOATS
                    if left_type in numeric_types and right_type in numeric_types and util.AUTOMATIC_CASTING:
                        node.type = types.choose_bigger_type(left_type, right_type)
                    else:
                        node.type = left.type
                else:
                    # Raises an error if types are not compatible
                    msg = (node.pos, "mismatch types ('{left_type}' vs '{right_type}')"
                           .format(left_type=left.type.name, right_type=right.type.name))
                    hints = ["Use 'as' keyword to convert values.",
                             "Create a magic method to convert implicitly the values."]
                    raise util.Error([msg], hints=hints)

    def visit_raise(self, node):
        self.visit(node.value)

    def visit_landingpad(self, node):
        # Check if all items on landing pad are Exception type
        for typ in node.map:
            typ = self.module.instance_type(typ, translations=self.translations)
            assert typ.name == "Exception"

    def visit_resume(self, node):
        pass

    def visit_call(self, node):

        # Make sure to visit all arguments in order to all arguments types be available
        for arg in node.args:
            self.visit(arg)

        # Callable can be a tuple contains a template object (class, method or function) to be derived and the
        # types to create the derived objects
        if node.callable.derivation_types is not None:
            infer_types = False
            derivation_types = [self.module.instance_type(tp, translations=self.translations)
                                for tp in node.callable.derivation_types]

        # Or just a callable object itself
        else:
            infer_types = True
            derivation_types = [types.unwrap(arg.type) for arg in node.args]

        positional, named = organize_args(node.args)

        # Find out the callable object, ie the function node
        node.callable_object = None
        if isinstance(node.callable, ast.Attribute):

            # Get the object type
            obj = node.callable.obj
            self.visit(obj)
            obj_type = types.unwrap(obj.type)
            assert isinstance(obj.type, types.Base), obj

            # Is it an attribute holding a function?
            if node.callable.attribute in obj_type.attributes:
                self.visit(node.callable)
                if isinstance(node.callable.type, types.Function):
                    node.callable_object = node.callable

            # Is it a normal method?
            elif node.callable.attribute in obj_type.methods:

                # Choose the class' method that fits the arguments' call
                node.callable_object = obj_type.select(self.module, node, node.callable.attribute, [None] + positional,
                                                       named, error_if_not_found=False)

            # In last case, is it a generator method?
            if node.callable_object is None:
                generator_name = obj_type.name.partition("<")[0] + "." + node.callable.attribute
                if generator_name in self.module.symbols:
                    node.callable_object = self.module.symbols[generator_name]

                else:
                    msg = (node.callable.obj.pos, "'{type}' does not have a method '{method}'"
                           .format(type=obj_type.name, method=node.callable.attribute))
                    hints = ["Check whether there is a typo in the name."]
                    raise util.Error([msg], hints=hints)

        # Is it a symbol which could be a function, class, or only a variable?
        else:
            node.callable_object = self.check_symbol_definition(node.callable, types_not_allowed=False)
            obj_type = None

        # There are four modes of call:
        #
        #   Class's method:
        #       res = obj.method()
        #
        #   Normal function:
        #       res = function()
        #
        #   Type constructor:
        #       res = Class()
        #
        #   Symbol holding a function:
        #       var function = other_function
        #       res = function()
        #
        # The code bellow will check which type of call is being executed and so perform type checking according to
        # the call

        # Calling a function or method:
        #     res = function()
        if isinstance(node.callable_object, ast.Function):
            node.fn = types.get_function(self.module, node.callable_object, infer_types, derivation_types,
                                         [None] + positional, named, self_type=obj_type)
            node.type = node.fn.type.over["ret"]

            # Mark the call as virtual if it's a trait
            if isinstance(obj_type, types.Trait):
                node.virtual = True

            # Insert the object as 'self' argument
            if obj_type is not None:
                node.args.insert(0, obj)
                positional.insert(0, obj.type)

        # Calling a type constructor:
        #     res = Class()
        elif isinstance(node.callable_object, (ast.Class, types.Base)):

            # Insert '$parent_self' argument in method generator
            is_method_as_generator = "." in node.callable_object.name
            if is_method_as_generator:
                parent_self_types = list(obj_type.type_vars.values())  # Include $parent_self derivation types
                derivation_types = derivation_types + parent_self_types
                node.args.append(obj)
                positional.append(obj.type)

            node.fn = types.get_constructor(self.module, node, node.callable_object, infer_types, derivation_types,
                                            [None] + positional, named, is_method_as_generator=is_method_as_generator)

            # Insert `self` as the first argument
            node.type = types.Wrapper(node.fn.self_type)
            if node.fn.name == "__init__":
                node.args.insert(0, ast.Init(node.type))
                positional.insert(0, node.type)

        # Calling a function hold by a variable or attribute:
        #     var function = other_function
        #     res = function()
        elif isinstance(node.callable_object.type, types.Function):
            node.fn = node.callable_object
            node.type = node.callable_object.type.over["ret"]

        else:
            msg = (node.callable.pos, "object is not a method or function (thus cannot be called)")
            raise util.Error([msg])

        # Traverse formal arguments of the function to check if some argument is missing in the call
        # Whether a formal argument is missing check if the formal argument has a default value to use it as
        # replacement
        names = {}
        if hasattr(node.fn, "args"):
            missing_args = []
            for arg_pos, formal_arg in enumerate(node.fn.args):
                if arg_pos > (len(positional) - 1) and formal_arg.name not in named:
                    if formal_arg.default_value is None:
                        missing_args.append(formal_arg)
                    else:
                        self.visit(formal_arg.default_value)
                        names[formal_arg.name] = formal_arg.default_value

            if len(missing_args) > 0:
                msg = (node.fn.pos, "function was declared with these arguments")
                msg2 = (node.pos, "but the call is missing the '{args}' argument(s)"
                        .format(args=", ".join("{arg}".format(arg=arg.name) for arg in missing_args)))
                raise util.Error([msg, msg2])

            # Rebuild arguments by putting named arguments in correct order
            new_args = []
            for arg in node.args:
                if isinstance(arg, ast.NamedArg):
                    names[arg.name] = arg.value
                else:
                    new_args.append(arg)
            for arg in list(node.fn.args)[len(new_args):]:
                new_args.append(names[arg.name])
            node.args = new_args

        # Check that the actual types match the function's formal types
        actuals = [arg.type for arg in node.args]
        formals = node.fn.type.over["args"]
        if not types.is_compatible(actuals, formals, "args", accept_bigger_type=False):
            actual_types = ", ".join("'{type}'".format(type=typ.name) for typ in actuals)
            formal_types = ", ".join("'{type}'".format(type=typ.name) for typ in formals)
            msg = (node.fn.pos, "formal argument(s) defined as {formals}".format(formals=formal_types))
            msg2 = (node.pos, "but {actuals} argument(s) passed in call"
                    .format(actuals=actual_types, formals=formal_types))
            hints = ["Use 'as' keyword to convert values.",
                     "Create a magic method to convert implicitly the values."]
            raise util.Error([msg, msg2], hints=hints)

    def visit_yield(self, node):
        self.visit(node.value)

        # Check if both destination (yield) and source (value) nodes have compatible types
        yield_type = self.fn.type.over["ret"]
        if not types.is_compatible(node.value.type, yield_type, "return", accept_bigger_type=False):
            msg = (self.fn.ret.pos, "function must yield a value of type '{formal}'".format(formal=yield_type.name))
            msg2 = (node.value.pos, "but yielded a value of type '{actual}'"
                    .format(actual=node.value.type.name))
            hints = ["Use 'as' keyword to convert values.",
                     "Create a magic method to convert implicitly the values."]
            raise util.Error([msg, msg2], hints=hints)

    def visit_return(self, node):
        if self.fn.has_context:
            if node.value is not None:
                msg = (self.fn.ret.pos, "function must yield a value because it is iterator")
                msg2 = (node.value.pos, "but return a value")
                hints = ["Use the 'yield' instead of 'return' keyword."]
                raise util.Error([msg, msg2], hints=hints)
            return

        # Check if None as return is ok
        ret_type = self.fn.type.over["ret"]
        if node.value is None and ret_type != self.module.instance_type("void"):
            hints = []
            if node.pos is None:
                msgs = [(self.fn.ret.pos, "function must return value of type '{type}' but no value was returned"
                        .format(type=ret_type.name))]
                hints = ["Return some value ('{type}') using 'return' keyword.".format(type=ret_type.name)]
            else:
                msg = (self.fn.ret.pos, "function must return value of type '{type}'"
                       .format(type=ret_type.name))
                msg2 = (node.pos, "but no value was returned here")
                msgs = [msg, msg2]
            hints += ["Do not define a return type for the function."]
            raise util.Error(msgs, hints=hints)
        elif node.value is not None and ret_type == self.module.instance_type("void"):
            self.visit(node.value)
            msg = (self.fn.pos, "function defined with no return")
            msg2 = (node.value.pos, "but is returning '{type}'".format(type=node.value.type.name))
            hints = ["Have you forget to define a return type for the function?"]
            raise util.Error([msg, msg2], hints=hints)
        elif node.value is None:
            return

        self.visit(node.value)

        # TODO: Doesn't allow reference to a local variable be returned as the local variable will be freed after call
        # is finished
        value_is_arg = isinstance(node.value, ast.Symbol) and \
                       node.value.get_name() in [arg.get_name() for arg in self.fn.args]
        if types.is_reference(node.value.type) and not value_is_arg:
            msg = (node.value.pos, "cannot return a reference to a local object")
            raise util.Error([msg])

        # Check if both destination (return) and source (value) nodes have compatible types
        if not types.is_compatible(node.value.type, ret_type, "return", accept_bigger_type=False):
            msg = (self.fn.ret.pos, "function must return a value of type '{formal}'".format(formal=ret_type.name))
            msg2 = (node.value.pos, "but returned a value of type '{actual}'".format(actual=node.value.type.name))
            hints = ["Use 'as' keyword to convert values.",
                     "Create a magic method to convert implicitly the values."]
            raise util.Error([msg, msg2], hints=hints)

    # Symbols

    def visit_symbol(self, node):
        symbol = self.check_symbol_definition(node)

        # If type was not specified then raises an error
        if symbol.type is None:
            msg = (symbol.pos, "no type was specified for the variable")
            hints = ["Declare the variable using the ': sometype' syntax.",
                     "Assign a value to variable in order to the type be inferred."]
            raise util.Error([msg], hints=hints)

        node.type = symbol.type

    def visit_namedarg(self, node):
        self.visit(node.value)
        node.type = node.value.type

    def visit_variabledeclaration(self, node):

        def set_variable_type(variable):

            # Add variable to function's scope
            self.define_variable(variable)

            if variable.type is not None:
                variable.type = types.check_wrapper(self.module.instance_type(variable.type, translations=self.translations))

        # Handle every element of the tuple
        if isinstance(node.variables, ast.Tuple):
            for i, element in enumerate(node.variables.elements):
                set_variable_type(element)

        # Handle the single variable
        elif isinstance(node.variables, ast.Symbol):
            set_variable_type(node.variables)

    def visit_assign(self, node):

        def check_void(right):
            if isinstance(right, ast.Call) and right.type == self.module.instance_type("void"):
                msg = (right.pos, "function returns nothing".format(type=right.type.name))
                raise util.Error([msg])

        def set_left_type(left, right_type):

            # Get the declared type of this node
            if isinstance(left, ast.Symbol):

                # Add hidden variables to function's scope
                if left.is_hidden():
                    self.define_variable(left)
                    left.type = right_type
                else:
                    symbol = self.check_symbol_definition(left)
                    if symbol.type is None:
                        symbol.type = right_type
                    self.visit(left)

            elif isinstance(left, (flow.SetAttribute, flow.SetElement)):

                # Infer the type attribute based on value assigned to it
                if isinstance(left, flow.SetAttribute):
                    self.visit(left.obj)
                    attribute = types.unwrap(left.obj.type).attributes[left.attribute]
                    if attribute["type"] is None:
                        attribute["type"] = right_type

                self.visit(left)

            # Check if variable and value have compatible types
            if not types.is_compatible(right_type, left.type, accept_bigger_type=False):
                msg = (node.right.pos, "mismatch types ('{right_type}' vs '{left_type}')"
                       .format(right_type=right_type.name, left_type=left.type.name))
                hints = ["Use 'as' keyword to convert values.",
                         "Create a magic method to convert implicitly the values."]
                raise util.Error([msg], hints=hints)

        self.visit(node.right)
        check_void(node.right)

        # Set the type for every element of the tuple
        if isinstance(node.left, ast.Tuple):
            if types.unwrap(node.right.type).name.startswith("tuple<"):
                num_right_elements = len(types.unwrap(node.right.type).elements)
            else:
                num_right_elements = 1
            num_left_elements = len(node.left.elements)
            if num_left_elements != num_right_elements:
                msg = (node.left.pos,
                       "number of elements ({num_left_elements}) exceeds the number of values to be assigned ({num_right_elements})".
                       format(num_left_elements=num_left_elements, num_right_elements=num_right_elements))
                raise util.Error([msg])

            node.left.type = node.right.type
            for i, element in enumerate(node.left.elements):
                element_type = types.unwrap(node.left.type).elements[i]
                if isinstance(node.right, ast.Tuple):
                    check_void(node.right.elements[i])
                set_left_type(element, element_type)

        # Set the type of the single variable, class's attribute or list's item
        elif isinstance(node.left, (ast.Symbol, flow.SetAttribute, flow.SetElement)):
            set_left_type(node.left, node.right.type)

        else:
            assert False, "Cannot assign to object"

    # Types

    def visit_as(self, node):
        self.visit(node.left)
        node.type = self.module.instance_type(node.right, translations=self.translations)

    def visit_isinstance(self, node):
        self.visit(node.obj)
        for i, typ in enumerate(node.types):
            node.types[i] = self.module.instance_type(typ, translations=self.translations)
        node.type = self.module.instance_type("bool")

    def visit_sizeof(self, node):
        node.target_type = self.module.instance_type(node.target_type, translations=self.translations)
        node.type = self.module.instance_type("anyint")

    def visit_transmute(self, node):
        self.visit(node.obj)
        node.type = types.check_wrapper(self.module.instance_type(node.type, translations=self.translations))

    # Memory manipulation

    def visit_del(self, node):
        self.visit(node.obj)

    def check_data_pointer(self, node):
        if not isinstance(types.unwrap(node.type), types.Data):
            msg = (node.pos, "object type must be 'data<T>' to perform this operation ('{type}' not allowed)"
                   .format(type=node.type.name))
            raise util.Error([msg])

    def visit_reallocmemory(self, node):
        self.visit(node.obj)
        self.check_data_pointer(node.obj)
        self.visit(node.num_elements)
        node.type = node.obj.type

    def visit_copymemory(self, node):
        self.visit(node.src)
        self.check_data_pointer(node.src)
        self.visit(node.dst)
        self.check_data_pointer(node.dst)
        self.visit(node.num_elements)

    def visit_movememory(self, node):
        self.visit(node.src)
        self.check_data_pointer(node.src)
        self.visit(node.dst)
        self.check_data_pointer(node.dst)
        self.visit(node.num_elements)

    def visit_reference(self, node):
        self.visit(node.value)
        node.type = types.Wrapper(node.value.type, is_reference=True)

    def visit_dereference(self, node):
        self.visit(node.value)
        if types.is_reference(node.value.type):
            node.type = node.value.type.over
        else:
            msg = (node.value.pos, "cannot dereference a non-reference value ('{type}')"
                   .format(type=node.value.type.name))
            hints = ["Only pointers created from '&' and '$' operators can be dereferenced."]
            raise util.Error([msg], hints=hints)

    def visit_offset(self, node):
        self.visit(node.obj)
        self.visit(node.idx)
        self.check_data_pointer(node.obj)
        node.type = node.obj.type

        if node.idx.type not in types.INTEGERS:
            msg = (node.idx.pos, "offset index must be a integer type ('{type}' not allowed)"
                   .format(type=node.idx.type.name))
            hints = ["Use 'as' keyword to convert values.",
                     "Create a magic method to convert implicitly the values."]
            raise util.Error([msg], hints=hints)
