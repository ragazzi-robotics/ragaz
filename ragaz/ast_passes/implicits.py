"""
This pass process the statements looking for code that need extra stuff to work.

For example, in this 'for' loop:
    for item in foo:

we first need get an iterator from 'foo' list, and then we begin the iteration. After that, we would need get the next
value from iterator at every iteration. So "behind the curtains", the 'for' loop become this:

    var foo_iterator = iter(foo)
    var item: some_type
    while True:
        try:
            item = next(foo_iterator)
        exception StopIteration:    # The iterator itself raises a StopIteration when is over
            break

Another job that this pass do, it's give unique names to variables with same names. For example, here:

    def foo(a: str):
        print(a)
        var a: int = 1
        if True:
            var a: float = 2.0
            print(a)
        print(a)

we have several variables with same name 'a'. This is what we call 'shadowing'. For the compiler to know which is which,
a distinct internal name will be assigned to each one. The function's argument 'a' will be called 'a$0', the first
local variable 'a' will be called 'a$1' and so on.
"""

import copy
from ragaz import ast_ as ast, util

PASS_NAME = __name__.split(".")[-1]


class ImplicitsProcessor(object):

    def __init__(self, module):
        self.module = module
        self.fn = None
        self.definitions = None
        self.generator_attributes = None

    def process(self):

        # Traverse the AST (abstract syntax tree) of the functions and process any implicit code found.
        for fn in self.module.functions:
            self.visit_function(fn)

    def define_variable(self, var):

        # Once several variables could use the same formal name, we must name them to a unique and internal name
        if "$" in var.name or var.name == "self":
            var.internal_name = var.name
        else:
            var.internal_name = var.name + self.fn.generate_suffix()

        if self.fn.is_generator and var.internal_name not in self.generator_attributes.keys() and var.name != "self":
            self.generator_attributes[var.internal_name] = var.pos, var.type

        self.definitions[var.name] = var.internal_name

    def create_generator_class(self):
        """
        Transform something like this:

            def range(start: int, stop: int):
                var num = start
                while num < stop:
                    yield num
                    num += 1

        Into this:

            class range:
                start: int
                stop: int
                num: int

                def __init__(self, start: int, stop: int):
                    self.start = start
                    self.stop = stop

                def __iter__(self) -> &Self:
                    return self

                def __next__(self) -> int:
                    self.num = self.start
                    while self.num < self.stop:
                        yield self.num
                        self.num += 1
        """
        type_vars = {}
        name = self.fn.name
        if self.fn.self_type is not None:
            name = self.fn.self_type.name + "." + name
            type_vars.update(self.fn.self_type.type_vars)
            self.fn.self_type.methods.remove(self.fn)
        type_vars.update(self.fn.type_vars)
        generator_class = ast.Class(None, [], name, type_vars, [], [])

        # Create the '__init__' function: it will receive the formal arguments from generator function
        args = copy.deepcopy(self.fn.args)
        if len(args) == 0 or args[0].name != "self":
            args.insert(0, ast.Argument(None, "self", internal_name="self"))
        if self.fn.self_type is not None:
            # When the function is a class method, its 'self' becomes an attribute called '$parent_self'. This new
            # object will reference the class instance which the generator manipulates
            if len(self.fn.self_type.type_vars) == 0:
                parent_self_type = ast.Type(None, self.fn.self_type.name)
            else:
                parent_self_type = ast.DerivedType(None, self.fn.self_type.name,
                                                   [ast.Type(None, typ.name) for typ in self.fn.self_type.type_vars.values()])
            parent_self_type = ast.Reference(None, parent_self_type)
            args.append(ast.Argument(None, "$parent_self", internal_name="$parent_self", typ=parent_self_type))
        init_fn = ast.Function(self.fn.pos, [], "__init__", {}, args, None)
        statements = []
        for arg in init_fn.args:
            if arg.internal_name != "self":
                attribute = ast.Attribute(None, ast.Symbol(None, "self", internal_name="self"), arg.internal_name)
                initial_value = ast.Symbol(None, arg.name, arg.type, arg.internal_name)
                statements.append(ast.Assign(None, attribute, initial_value))
        init_fn.suite = ast.Suite(None, statements)
        self.module.functions.append(init_fn)

        # Create the '__iter__' function: it will return the generator instance itself
        args = [ast.Argument(None, "self", internal_name="self")]
        ret = ast.Reference(None, ast.Type(None, "Self"))
        attribute = ast.Attribute(None, ast.Symbol(None, "self", internal_name="self"), "$iteration_started")
        initial_value = ast.Bool(None, False)
        iteration_started_assignment = ast.Assign(None, attribute, initial_value)
        return_node = ast.Return(None, ast.Symbol(None, "self", internal_name="self"))
        statements = [iteration_started_assignment, return_node]
        iter_fn = ast.Function(None, [], "__iter__", {}, args, ret)
        iter_fn.suite = ast.Suite(None, statements)
        self.module.functions.append(iter_fn)

        # Create the '__next__' function: it will be created a copy of the original function but:
        #   1. Removing its formal arguments because they already passed in '__init__'
        #   2. Changing its return type to 'iterator<T>' to just 'T'.
        args = [ast.Argument(None, "self", internal_name="self")]
        ret = self.fn.ret
        if len(ret.types) == 1:
            ret = ret.types[0]
        else:
            ret = ast.DerivedType(ret.pos, "tuple", ret.types)
        statements = copy.deepcopy(self.fn.suite.statements)
        next_fn = ast.Function(None, [], "__next__", {}, args, ret)
        next_fn.suite = ast.Suite(None, statements)
        next_fn.has_context = True
        self.module.functions.append(next_fn)
        self.module.functions.remove(self.fn)

        # Putting '$parent_self' as the attribute of the generator
        # This object will reference the class instance which the generator manipulates
        if self.fn.self_type is not None:
            name = ast.Name(None, "$parent_self")
            typ = parent_self_type
            generator_class.attributes.append((typ, name))

        # Putting '$iteration_started' as the attribute of the generator
        name = ast.Name(None, "$iteration_started")
        typ = ast.Type(None, "bool")
        generator_class.attributes.append((typ, name))

        # Putting '$next_block' as the attribute of the generator to store the address of the new block that will be
        # jumped as soon the function is called again
        name = ast.Name(None, "$next_block")
        typ = ast.DerivedType(None, "data", [ast.Type(None, "byte")])
        generator_class.attributes.append((typ, name))

        # Add the new generator attributes
        for name, (pos, typ) in self.generator_attributes.items():
            generator_class.attributes.append((typ, ast.Name(pos, name)))

        # Add the new generator methods
        generator_class.methods = [init_fn, iter_fn, next_fn]

        self.module.symbols[generator_class.name] = generator_class

    # General

    def visit(self, node):
        """
        This is used for call the proper visit method for a node. If node, for instance, is an ast.String, then
        this method will call `visit_string` method to handle the node properly.
        """
        fn_name = "visit_" + str(node.__class__.__name__).lower()
        visit_node_fn = getattr(self, fn_name)
        return visit_node_fn(node)

    def visit_function(self, fn):
        """
        Start the analysis.
        """
        if PASS_NAME not in fn.passes:

            self.fn = fn
            self.definitions = util.ScopesDict()
            self.generator_attributes = {}

            # Add arguments to function's scope
            arg_default_found = None
            for arg in fn.args:
                if arg.default_value is None:
                    if arg_default_found is not None:
                        msg = (arg.pos, "non-default arguments must come before default arguments")
                        hints = ["Move '{ordered_arg}' to front of '{default_arg}'".
                                 format(ordered_arg=arg.name, default_arg=arg_default_found.name)]
                        raise util.Error([msg], hints=hints)
                else:
                    arg_default_found = arg
                self.define_variable(arg)

            # Visit all steps for find the implicits
            fn.suite = self.visit(fn.suite)

            # If this is a generator (once function has yields) prepare a generator type
            if fn.is_generator:
                self.create_generator_class()

        fn.passes.append(PASS_NAME)
        return fn

    def visit_suite(self, node):
        def add_statements(statements):
            if isinstance(statements, list):
                for statement in statements:
                    add_statements(statement)
            else:
                updated_statements.append(statements)
            return statements

        self.definitions = util.ScopesDict(self.definitions)

        updated_statements = []
        for statement in node.statements:

            # Visit the current statement
            statements = self.visit(statement)
            add_statements(statements)

        node.statements = updated_statements
        self.definitions = self.definitions.parent
        return node

    def unary_op(self, node):
        node.value = self.visit(node.value)
        return node

    def binary_op(self, node):
        node.left = self.visit(node.left)
        node.right = self.visit(node.right)
        return node

    # Basic types

    def visit_noneval(self, node):
        return node

    def visit_bool(self, node):
        return node

    def visit_int(self, node):
        return node

    def visit_float(self, node):
        return node

    def visit_byte(self, node):
        return node

    # Structures

    def visit_array(self, node):
        node.num_elements = self.visit(node.num_elements)
        return node

    def visit_string(self, node):
        return node

    def visit_tuple(self, node):
        node.elements = [self.visit(element) for element in node.elements]
        return node

    def visit_list(self, node):
        node.elements = [self.visit(element) for element in node.elements]
        return node

    def visit_dict(self, node):
        elements = {}
        for key, value in node.elements.items():
            key = self.visit(key)
            value = self.visit(value)
            elements[key] = value
        node.elements = elements
        return node

    def visit_set(self, node):
        node.elements = [self.visit(element) for element in node.elements]
        return node

    def visit_attribute(self, node):

        def mount_namespaced_object(n, path=""):
            """
            Mount the full namespace to check if object makes part of an imported module
            """
            if isinstance(n, ast.Symbol):
                path += n.name
            elif isinstance(n, ast.Attribute):
                path += mount_namespaced_object(n.obj, path) + "." + n.attribute
            return path

        # Check if it is an imported object...
        namespaced = mount_namespaced_object(node)
        if namespaced in self.module.symbols:
            return ast.Symbol(node.pos, namespaced)

        # ...or an object's attribute
        else:
            if self.fn.is_generator and isinstance(node.obj, ast.Symbol) and node.obj.get_name() == "self":
                pos, obj, attribute = node.pos, ast.Symbol(node.pos, "self", internal_name="self"), "$parent_self"
                node.obj = ast.Attribute(pos, obj, attribute)
            else:
                node.obj = self.visit(node.obj)
            return node

    def visit_element(self, node):
        node.obj = self.visit(node.obj)
        node.key = self.visit(node.key)
        return node

    def visit_setelement(self, node):
        return self.visit_element(node)

    # Boolean operators

    def visit_not(self, node):
        return self.unary_op(node)

    def visit_and(self, node):
        return self.binary_op(node)

    def visit_or(self, node):
        return self.binary_op(node)

    # Comparison operators

    def visit_in(self, node):
        node = ast.Call(None, ast.Attribute(None, node.right, "__contains__"), [node.left])
        node = self.visit(node)
        return node

    def visit_is(self, node):
        return self.binary_op(node)

    def visit_equal(self, node):
        return self.binary_op(node)

    def visit_notequal(self, node):
        return self.binary_op(node)

    def visit_lowerthan(self, node):
        return self.binary_op(node)

    def visit_lowerequal(self, node):
        return self.binary_op(node)

    def visit_greaterthan(self, node):
        return self.binary_op(node)

    def visit_greaterequal(self, node):
        return self.binary_op(node)

    # Arithmetic operators

    def visit_neg(self, node):
        return self.unary_op(node)

    def visit_add(self, node):
        return self.binary_op(node)

    def visit_sub(self, node):
        return self.binary_op(node)

    def visit_mod(self, node):
        return self.binary_op(node)

    def visit_mul(self, node):
        return self.binary_op(node)

    def visit_div(self, node):
        return self.binary_op(node)

    def visit_floordiv(self, node):
        return self.binary_op(node)

    def visit_pow(self, node):
        return self.binary_op(node)

    # Bitwise operators

    def visit_bwnot(self, node):
        return self.unary_op(node)

    def visit_bwand(self, node):
        return self.binary_op(node)

    def visit_bwor(self, node):
        return self.binary_op(node)

    def visit_bwxor(self, node):
        return self.binary_op(node)

    def visit_bwshiftleft(self, node):
        return self.binary_op(node)

    def visit_bwshiftright(self, node):
        return self.binary_op(node)

    # Control flow

    def visit_pass(self, node):
        return node

    def visit_ternary(self, node):
        node.cond = self.visit(node.cond)
        node.values[0] = self.visit(node.values[0])
        node.values[1] = self.visit(node.values[1])
        return node

    def visit_if(self, node):
        for part in node.parts:
            if part["cond"] is not None:
                part["cond"] = self.visit(part["cond"])
            part["suite"] = self.visit(part["suite"])
        return node

    def visit_while(self, node):
        node.cond = self.visit(node.cond)
        node.suite = self.visit(node.suite)
        return node

    def visit_for(self, node):

        """
        Transform this:
        for item in some_list:
            print(item)

        Into this:
        var iterator = iter(some_list)
        var item
        while True:
            try:
                item = next(iterator)
            except Exception:
                break
            print(item)
        """

        # Create the iterator assignment
        iterator_var = ast.Symbol(None, name="iterator")
        iter_call = ast.Call(None, ast.Attribute(None, node.source, "__iter__"), [])
        iterator_assignment = ast.Assign(None, iterator_var, iter_call)

        # Create a declaration for the iterator variable
        iterator_declaration = ast.VariableDeclaration(None, iterator_var)
        iterator_declaration.assignment = iterator_assignment
        iterator_declaration = self.visit(iterator_declaration)

        # Create the statement to try to update the loop variable
        next_call = ast.Call(None, ast.Attribute(None, iterator_var, "__next__"), [])
        loop_var_assignment = ast.Assign(None, node.loop_var, next_call)
        try_suite = ast.Suite(None, [loop_var_assignment])

        # Create a declaration for the loop variable. The type of the variable only will be known in the assignment
        # of if to the call to '__next__' function.
        loop_var_declaration = ast.VariableDeclaration(None, node.loop_var)
        loop_var_declaration = self.visit(loop_var_declaration)

        # If a 'StopIteration' is raised then exit the loop using 'break' statement
        break_statement = ast.Break(None)
        except_suite = ast.Suite(None, [break_statement])
        handler = ast.Except(None, ast.Type(None, "Exception"), except_suite)  # TODO: Use StopIteration exception

        # Create the 'try' statement to update the loop variable and set it as first statement in the while suite
        try_update_loop_var = ast.TryBlock(None, try_suite, handler)
        node.suite.statements.insert(0, try_update_loop_var)

        # Create the 'while' statement where condition is always True and will stop only when 'StopIteration'
        # is caught
        # The suite of statements of this new loop is the 'try' statement to get the next value from iterator plus
        # the statements from former 'for' loop
        cond = ast.Bool(None, "True")
        node = ast.While(node.pos, cond, node.suite)

        # Now, once the 'for' loop was converted to 'while', process it
        node = self.visit(node)

        return [iterator_declaration, loop_var_declaration, node]

    def visit_break(self, node):
        return node

    def visit_continue(self, node):
        return node

    def visit_raise(self, node):
        return node

    def visit_tryblock(self, node):
        node.suite = self.visit(node.suite)
        for handler in node.catch:
            handler.suite = self.visit(handler.suite)
        return node

    def visit_call(self, node):
        node.callable = self.visit(node.callable)
        for i, arg in enumerate(node.args):
            node.args[i] = self.visit(arg)
        return node

    def visit_yield(self, node):
        if node.value is not None:
            node.value = self.visit(node.value)
        return node

    def visit_return(self, node):
        if node.value is not None:
            node.value = self.visit(node.value)
        return node

    # Symbols

    def visit_symbol(self, node):
        if node.name in self.definitions:
            internal_name = self.definitions[node.name]
            if self.fn.is_generator and not node.is_hidden():
                pos, obj, attribute = node.pos, ast.Symbol(node.pos, "self", internal_name="self"), internal_name
                node = ast.Attribute(pos, obj, attribute)
            else:
                node.internal_name = internal_name
        return node

    def visit_namedarg(self, node):
        node.value = self.visit(node.value)
        return node

    def visit_variabledeclaration(self, node):
        statements = []

        for i, statement in enumerate(decompose_variable_declaration(node)):

            if isinstance(statement, ast.VariableDeclaration):
                declaration = statement

                # NOTE: The right side of the assignment must be visited before the variable definition to avoid the
                # compiler use the new symbol declared instead of a symbol declared earlier. For example, here:
                #
                #    var a = foo(a)
                #
                # the 'a' passed as argument is the current symbol with same name (and with a unique internal name) while
                # the 'a' as variable receiving the call's value will be a new symbol with same name (but also with other
                # internal name)
                if declaration.assignment is not None:
                    declaration.assignment.right = self.visit(declaration.assignment.right)

                # Add every element of the tuple to function's scope
                if isinstance(declaration.variables, ast.Tuple):
                    for i, element in enumerate(declaration.variables.elements):
                        self.define_variable(element)

                # Add the single variable to function's scope
                elif isinstance(declaration.variables, ast.Symbol):
                    self.define_variable(declaration.variables)

                # Now once the variable was defined, we could name the left side with new internal name
                if declaration.assignment is not None:
                    declaration.assignment.left = self.visit(declaration.assignment.left)

                if self.fn.is_generator:
                    if declaration.assignment is not None:
                        statements.append(declaration.assignment)
                else:
                    statements.append(declaration)

            else:
                statement = self.visit(statement)
                statements.append(statement)

        return statements

    def visit_assign(self, node):
        assignments = []
        for assignment in decompose_assignment(node):
            assignment.left = self.visit(assignment.left)
            assignment.right = self.visit(assignment.right)
            assignments.append(assignment)
        return assignments

    def visit_inplace(self, node):
        assignment = ast.Assign(node.pos, copy.copy(node.operation.left), node.operation)
        assignment = self.visit(assignment)
        return assignment

    # Types

    def visit_as(self, node):
        node.left = self.visit(node.left)
        return node

    def visit_isinstance(self, node):
        node.obj = self.visit(node.obj)
        return node

    def visit_sizeof(self, node):
        return node

    def visit_transmute(self, node):
        node.obj = self.visit(node.obj)
        return node

    # Memory manipulation

    def visit_del(self, node):
        node.obj = self.visit(node.obj)
        return node

    def visit_reallocmemory(self, node):
        node.obj = self.visit(node.obj)
        node.num_elements = self.visit(node.num_elements)
        return node

    def visit_copymemory(self, node):
        node.src = self.visit(node.src)
        node.dst = self.visit(node.dst)
        node.num_elements = self.visit(node.num_elements)
        return node

    def visit_movememory(self, node):
        node.src = self.visit(node.src)
        node.dst = self.visit(node.dst)
        node.num_elements = self.visit(node.num_elements)
        return node

    def visit_reference(self, node):
        return self.unary_op(node)

    def visit_dereference(self, node):
        return self.unary_op(node)

    def visit_offset(self, node):
        node.obj = self.visit(node.obj)
        node.idx = self.visit(node.idx)
        return node


def decompose_assignment_with_tuple(node, from_declaration):
    # Transform this:
    # a, b, c = 1, 2, 3
    #
    # Into this:
    # a = 1
    # b = 2
    # c = 3
    assignments = []
    if isinstance(node.left, ast.Tuple) and isinstance(node.right, ast.Tuple) and \
            len(node.left.elements) == len(node.right.elements):
        for left, right in zip(node.left.elements, node.right.elements):
            assignment = ast.Assign(node.pos, left, right)
            if from_declaration:
                assignments.append(ast.VariableDeclaration(node.pos, copy.copy(left), assignment))
            else:
                assignments.append(assignment)
    else:
        if from_declaration:
            assignments.append(ast.VariableDeclaration(node.pos, copy.copy(node.left), node))
        else:
            assignments.append(node)
    return assignments


def decompose_assignment(node, from_declaration=False):
    # Transform this:
    # a = b = c
    #
    # Into this:
    # b = c
    # a = b
    assignments = []
    if isinstance(node.right, ast.Assign):
        right = copy.deepcopy(node.right.left)
        assignments.extend(decompose_assignment(node.right))
        node = ast.Assign(node.pos, node.left, right)
    assignments.extend(decompose_assignment_with_tuple(node, from_declaration))
    return assignments


def decompose_variable_declaration(node):
    # Transform this:
    # var a, b, c = 1, 2, 3
    #
    # Into this:
    # var a = 1
    # var b = 2
    # var c = 3
    if node.assignment is None:
        statements = []
        if isinstance(node.variables, ast.Tuple):
            for variable in node.variables.elements:
                declaration = ast.VariableDeclaration(node.pos, variable)
                statements.append(declaration)
        else:
            statements.append(node)
    else:
        statements = decompose_assignment(node.assignment, True)

    return statements
