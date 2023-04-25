"""
This pass inserts calls to free objects after their end of scope is reached.

When we create a variable, a portion of memory is allocated to it. However, this portion must be immediately freed
after the same went out of scope. But many times a given data needs escape from this cleaning to be used in
other instructions beyond the scope. To this, we allocate this data on the heap and mark it as 'escaping object'. While
all those objects not marked to escape, it will be freed after scope is gone.

Look how this pass work seeing this example before it be processed by the 'destructor':

    def foo():
        var b = "Dirty Deeds"
        if True:
            var a = "Done"
            var c = "Dirt Cheap"
            b = a

Now after the pass:

    def foo():
        var b = "Dirty Deeds"
        if True:
            var a = "Done"
            var c = "Dirt Cheap"
            DEL(b) # This will free 'Dirty Deeds' string on the heap...
            b = a  # ...because now 'b' owns 'a's content, ie 'Done' string and 'Dirty Deeds' got orphaned
            DEL(c)  # Free 'Dirt Cheap' once 'c' won't escape from scope
        DEL(b)  # Now finally free 'Done' string was moved earlier to 'b'

In the example above, note that there's not 'DEL(a)' after scope is gone. This happens because once the heap content
that 'a' was referencing became a property of 'b', it does not make senses create a `Del` node to 'a':

<<It's important know that although 'a' references a heap content, 'a' itself is just a variable allocated in the
stack memory. Thus, it will be automatically destructed when the call is done. In other words, we use `Del` nodes
only for stack-allocated variables that own any data on the heap memory.>>
"""

import copy
from ragaz import ast_ as ast, util, types_ as types
from ragaz.ast_passes import flow

PASS_NAME = __name__.split(".")[-1]


class Definition:
    def __init__(self, var, initialized):
        self.var = var
        self.initialized = initialized


class Destructor(object):

    def __init__(self, module):
        self.module = module
        self.fn = None
        self.definitions = None
        self.curr_block, self.curr_step = None, None

    def process(self):

        # Visit the actual function code finding freeings of variables on its statements
        for fn in self.module.functions:
            self.visit_function(fn)

    def define_variable(self, var, initialized=False):
        if var.get_name() not in self.definitions:
            self.definitions[var.get_name()] = Definition(var, initialized)

    def check_delete_variable(self, var, reassign=False):
        if types.is_wrapped(var.type) and not types.is_reference(var.type) and (not var.must_escape or reassign):
            node = copy.copy(var)
            self.curr_block.insert_step(self.curr_step, ast.Del(var.pos, node))

    def visit(self, node):
        """
        This is used for call the proper visit method for a node. If node, for instance, is an ast.String, then
        this method will call `visit_string` method to handle the node properly.
        """
        if node is None:
            return

        # Call the "visit" function of the node if it exists
        fn_name = "visit_" + str(node.__class__.__name__).lower()
        if hasattr(self, fn_name):
            visit_node_fn = getattr(self, fn_name)
            visit_node_fn(node)

    def visit_function(self, fn):
        """
        Start the analysis.
        """
        if PASS_NAME not in fn.passes and types.is_concrete(fn):
            self.fn = fn
            self.definitions = util.ScopesDict()
            self.curr_block, self.curr_step = None, None

            # Add attributes to function's scope
            if self.fn.self_type is not None:
                for attribute in self.fn.self_type.attributes:
                    attribute = ast.Attribute(None,
                                              ast.Symbol(None, "self", internal_name="self", typ=self.fn.self_type),
                                              attribute)
                    initialized = self.fn.name != "__init__"
                    self.define_variable(attribute, initialized)

            # Add arguments to function's scope
            for arg in self.fn.args:
                # Let's create a symbol for the argument and so avoid create `visit_argument` functions in the passes
                # `visit_symbol` has all code needed to handle arguments
                arg_as_symbol = ast.Symbol(arg.pos, arg.name, typ=arg.type, internal_name=arg.internal_name)
                arg_as_symbol.must_escape = arg.must_escape
                self.define_variable(arg_as_symbol, True)

            # Check which nodes can be freed
            for block in sorted(self.fn.flow.blocks, key=lambda blk: blk.id):
                for step in sorted(block.steps, key=lambda stp: stp.id):
                    self.curr_block, self.curr_step = block, step
                    self.visit(step)

            # Check which attributes are uninitialized in case of the function be a constructor
            if self.fn.self_type is not None and self.fn.name == "__init__":
                non_initialized = []
                for attribute in self.fn.self_type.attributes:
                    definition = self.definitions[("self", attribute)]
                    if not definition.initialized and attribute != "id" and "$" not in attribute:
                        non_initialized.append(attribute)
                if len(non_initialized) > 0:
                    attributes = ", ".join("'{attribute}'".format(attribute=attribute) for attribute in non_initialized)
                    msg = (self.fn.pos, "the following attributes were not initialized in this method: "
                                        "{attributes}".format(attributes=attributes))
                    raise util.Error([msg])

        fn.passes.append(PASS_NAME)

    def visit_beginscope(self, node):

        # Create a scope object for variable definitions; this is crucial for find a local variable's name in
        # the scopes of a function
        self.definitions = util.ScopesDict(self.definitions)

        return node

    def visit_endscope(self, node):

        # We don't need to free any variable when the last step of the block is a `Return`: this is because when the
        # function returns, all variable allocated (not matter the scope) until the return point already were freed.
        if not isinstance(self.curr_block.last_step(), ast.Return):

            # Free all variables allocated in this scope
            for definition in self.definitions.current.values():
                self.check_delete_variable(definition.var)

        self.definitions = self.definitions.parent
        return node

    # Basic types

    def visit_noneval(self, node):
        pass

    def visit_bool(self, node):
        pass

    def visit_int(self, node):
        pass

    def visit_float(self, node):
        pass

    def visit_byte(self, node):
        pass

    # Structures

    def visit_array(self, node):
        self.visit(node.num_elements)

    def visit_string(self, node):
        pass

    def visit_tuple(self, node):
        for element in node.elements:
            self.visit(element)

    def visit_list(self, node):
        for element in node.elements:
            self.visit(element)

    def visit_dict(self, node):
        for key, value in node.elements.items():
            self.visit(key)
            self.visit(value)

    def visit_set(self, node):
        for element in node.elements:
            self.visit(element)

    def visit_attribute(self, node):
        self.visit(node.obj)

    def visit_setattribute(self, node):
        self.visit_attribute(node)

    def visit_element(self, node):
        self.visit(node.obj)
        self.visit(node.key)

    def visit_setelement(self, node):
        self.visit_element(node)

    # Boolean operators

    def visit_not(self, node):
        self.visit(node.value)

    def boolean(self, node):
        self.visit(node.left)
        self.visit(node.right)

    def visit_and(self, node):
        self.boolean(node)

    def visit_or(self, node):
        self.boolean(node)

    # Comparison operators

    def visit_is(self, node):
        self.visit(node.left)

    def compare(self, node):
        self.visit(node.left)
        self.visit(node.right)

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

    def visit_neg(self, node):
        self.visit(node.value)

    def visit_add(self, node):
        self.arith(node)

    def visit_sub(self, node):
        self.arith(node)

    def visit_mod(self, node):
        self.arith(node)

    def visit_mul(self, node):
        self.arith(node)

    def visit_div(self, node):
        self.arith(node)

    def visit_floordiv(self, node):
        self.arith(node)

    def visit_pow(self, node):
        self.arith(node)

    # Bitwise operators

    def bitwise(self, node):
        self.visit(node.left)
        self.visit(node.right)

    def visit_bwnot(self, node):
        self.visit(node.value)

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
        pass

    def visit_condbranch(self, node):
        self.visit(node.cond)

    def visit_phi(self, node):
        self.visit(node.left[1])
        self.visit(node.right[1])

    def visit_raise(self, node):
        pass

    def visit_landingpad(self, node):
        pass

    def visit_resume(self, node):
        pass

    def visit_call(self, node):
        self.visit(node.callable)
        for arg in node.args:
            self.visit(arg)

    def visit_yield(self, node):
        self.visit(node.value)

    def visit_return(self, node):
        self.visit(node.value)

        # Free all variables allocated (in this scope and in the outer scopes) until this point
        for definition in self.definitions.values():
            self.check_delete_variable(definition.var)

        # TODO: Does it really set free the args of main as they will be destructed when the program is over?
        # # Free 'argc' and 'argv' arguments of the 'main' function
        # if self.fn.get_name() == "main" and len(self.fn.args) > 0:
        #     argc, argv = None, None
        #     for arg in self.fn.args:
        #         if arg.name == "argc":
        #             argc = arg
        #         elif arg.name == "argv":
        #             argv = arg
        #     self.check_delete_variable(argc)
        #     self.check_delete_variable(argv)

    # Symbols

    def visit_symbol(self, node):
        pass

    def visit_namedarg(self, node):
        self.visit(node.value)

    def visit_variabledeclaration(self, node):
        pass

    def visit_assign(self, node):

        def assign_variable(left):

            if isinstance(left, (ast.Symbol, flow.SetAttribute)):

                # TODO: Check a better way to free the current content of a variable when this is receiving a new value
                # to be stored. A solution is this bellow, but is presenting problems. the other solution is free the
                # content in the code generation pass, but first it's necessary check if the variable already received
                # content stored in heap memory
                # # If a variable that owns a heap allocated value is reassigned then its content must be freed on
                # # heap memory
                # if left.get_name() in self.definitions:
                #     definition = self.definitions[left.get_name()]
                #     if definition.initialized:
                #         self.check_delete_variable(definition.var, reassign=True)

                 if isinstance(left, ast.Symbol):
                     self.define_variable(left)

            # TODO: Check a better way to free the current content of a element or attribute
            # elif isinstance(left, flow.SetElement):
            #
            #     # If a variable that owns a heap allocated value is reassigned then its content must be freed on
            #     # heap memory
            #     self.check_delete_variable(left, reassign=True)

            if left.get_name() in self.definitions:
                definition = self.definitions[left.get_name()]
                definition.initialized = True

        self.visit(node.right)

        # Handle every element of the tuple
        if isinstance(node.left, ast.Tuple):
            for i, element in enumerate(node.left.elements):
                assign_variable(element)

        # Handle the single variable
        elif isinstance(node.left, (ast.Symbol, flow.SetAttribute, flow.SetElement)):
            assign_variable(node.left)

    # Types

    def visit_as(self, node):
        self.visit(node.left)

    def visit_isinstance(self, node):
        self.visit(node.obj)

    def visit_sizeof(self, node):
        pass

    def visit_transmute(self, node):
        self.visit(node.obj)

    # Memory manipulation

    def visit_del(self, node):
        self.visit(node.obj)

        # If a variable that owns a heap allocated value is deleted then its content must be freed on
        # heap memory and this one must be removed from definitions list to avoid that it be freed again when
        # scope is gone
        if isinstance(node.obj, ast.Symbol) and node.obj.get_name() in self.definitions:
            del self.definitions[node.obj.get_name()]

    def visit_reallocmemory(self, node):
        self.visit(node.obj)
        self.visit(node.num_elements)

    def visit_copymemory(self, node):
        self.visit(node.src)
        self.visit(node.dst)
        self.visit(node.num_elements)

    def visit_movememory(self, node):
        self.visit(node.src)
        self.visit(node.dst)
        self.visit(node.num_elements)

    def visit_reference(self, node):
        self.visit(node.value)

    def visit_dereference(self, node):
        self.visit(node.value)

    def visit_offset(self, node):
        self.visit(node.obj)
        self.visit(node.idx)
