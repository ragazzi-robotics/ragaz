"""
This pass walks the CFG looking for 'moves' and 'borrowings' of variables and whether there are conflicts
involving the same.

One of the checks is about the use of variable that moved earlier to another variable or into arguments for
a function call:

    var a = "blah"
    var b = a
    print(a)  # Compiler raises an error once 'a's value was moved 'b' and now 'a' is inaccessible from that point.

Another check is about an already referenced variable received a new value:

    var a = "blah"
    var b = &a  # 'b' is referencing the 'a's content, ie "blah"
    a = "ops!"  # But now 'a's content is "ops!" and "blah" is freed on heap
    print(b)  # Compiler raises an error because 'b' is referencing empty content because "blah" was freed

"""

from ragaz import ast_ as ast, util, types_ as types
from ragaz.ast_passes import flow

PASS_NAME = __name__.split(".")[-1]


class UsesChecker(object):

    def __init__(self, module):
        self.module = module
        self.fn = None
        self.indent_level = None
        self.definitions = None
        self.uses = None
        self.moves = None
        self.references = None

    def process(self):

        # Visit the actual function code finding definitions and uses of variables on its statements
        for fn in self.module.functions:
            self.visit_function(fn)

    def define_variable(self, var):
        if var.get_name() not in self.definitions:
            self.definitions[var.get_name()] = self.indent_level, var
        if var.name != "self" and (isinstance(var, ast.Symbol) and not var.is_hidden()):
            self.uses[var.get_name()] = var, set()

    def check_move_or_copy(self, src, dst_type):

        def check_partial_move(node):
            # Check if object had its ownership moved
            var = self.moves.get(node.get_name(), None)
            if var is None:
                for obj in self.moves:
                    if isinstance(obj, tuple) and obj[0] == node.get_name():
                        var = self.moves[obj]
                        msg = (var.pos, "value partially moved here")
                        msg2 = (node.pos, "but passed again here after move")
                        hints = ["If you don't intend move it, consider pass a reference to value using '&' operator."]
                        raise util.Error([msg, msg2], hints=hints)

        # If the object will be passed to a function which is imported from C language, the operations like 'move'
        # and 'copy' are not applicable
        is_extern_c = False
        if hasattr(src, "copy_or_move_call") and src.copy_or_move_call is not None:
            is_extern_c = src.copy_or_move_call.fn.type.is_extern_c

        # If object will be moved, render it inaccessible after now
        if not is_extern_c:
            if hasattr(src, "check_move") and src.check_move:
                if types.is_heap_owner(dst_type):
                    if isinstance(src, ast.Tuple):
                        for i, element in enumerate(src.elements):
                            if types.is_heap_owner(element.type):
                                check_partial_move(element)
                                self.moves[element.get_name()] = element
                    elif isinstance(src, (ast.Symbol, ast.Attribute)):
                        check_partial_move(src)
                        self.moves[src.get_name()] = src
            elif hasattr(src, "check_copy") and src.check_copy:
                if not types.is_heap_owner(src.type):
                    src.check_copy = False
        else:
            if hasattr(src, "check_move"):
                src.check_move = False
            elif hasattr(src, "check_copy"):
                src.check_copy = False

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
        util.check_previous_pass(self.module, fn, PASS_NAME)
        if PASS_NAME not in fn.passes and types.is_concrete(fn):
            self.fn = fn
            self.indent_level = -1
            self.definitions = util.ScopesDict()
            self.uses = {}
            self.moves = {}
            self.references = {}

            # Add arguments to function's scope
            for arg in self.fn.args:
                self.define_variable(arg)

            # Check where names were assigned and where were used
            for block in sorted(self.fn.flow.blocks, key=lambda blk: blk.id):
                for step in sorted(block.steps, key=lambda stp: stp.id):
                    self.visit(step)

            # Check which variables are unused
            for name in self.uses:
                var, uses = self.uses[name]
                if len(uses) == 0:
                    msg = (var.pos, "this variable is unused")
                    util.warn([msg])
                    break

        fn.passes.append(PASS_NAME)

    def visit_beginscope(self, node):
        self.definitions = util.ScopesDict(self.definitions)
        self.indent_level += 1

    def visit_endscope(self, node):
        self.definitions = self.definitions.parent
        self.indent_level -= 1
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
        for i, element in enumerate(node.elements):
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
        if isinstance(node.obj, ast.Symbol):
            self.check_object(node)
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
        self.visit(node.value)

    def visit_landingpad(self, node):
        pass

    def visit_resume(self, node):
        pass

    def visit_call(self, node):
        self.visit(node.callable)

        formals = node.fn.type.over["args"]
        for actual, formal_type in zip(node.args, formals):
            self.visit(actual)
            self.check_move_or_copy(actual, formal_type)

    def visit_yield(self, node):
        self.visit(node.value)

    def visit_return(self, node):
        self.visit(node.value)

    # Symbols

    def check_object(self, node):

        # Check if variable had its ownership moved
        var = self.moves.get(node.get_name(), None)
        if var is not None:
            msg = (var.pos, "value moved here")
            msg2 = (node.pos, "but used here after move")
            hints = ["If you don't intend move it, consider pass a reference to value using '&' operator."]
            raise util.Error([msg, msg2], hints=hints)

        # Check if object is being used after the referenced object received new value
        for _, references in self.references.items():
            for i in range(len(references)):
                reference_assign = references[i]["reference_assign"]
                blocking_assign = references[i]["blocking_assign"]
                if references[i]["obj"].get_name() == node.get_name() and blocking_assign is not None:
                    _, var = self.definitions[blocking_assign.left.get_name()]
                    msg = (reference_assign.right.pos, "when an object is referenced".format(var=var.name))
                    msg2 = (blocking_assign.left.pos, "but new assignment to it happens".format(var=var.name))
                    msg3 = (node.pos, "the reference cannot be used later")
                    raise util.Error([msg, msg2, msg3])

    def visit_symbol(self, node):
        self.check_object(node)

        # Check if variable is used and increments the counter
        if node.get_name() in self.uses:
            var, uses = self.uses[node.get_name()]
            uses.add(node)

    def visit_namedarg(self, node):
        self.visit(node.value)

    def visit_variabledeclaration(self, node):

        # Define every element of the tuple
        if isinstance(node.variables, ast.Tuple):
            for element in node.variables.elements:
                self.define_variable(element)

        # Define the single variable
        else:
            self.define_variable(node.variables)

    def visit_assign(self, node):

        def check_object_blockings(left):
            def block_references(obj):
                if obj.get_name() in self.references:
                    references = self.references[obj.get_name()]
                    for i in range(len(references)):
                        references[i]["blocking_assign"] = node
                        block_references(references[i]["obj"])

            # Block any variable which references the variable to be used from this point
            # This is important to avoid references to freed memory
            block_references(left)

            # Once variable is owning a new value, from this place doesn't make sense keep checking if the
            # variable was moved earlier
            if left.get_name() in self.moves:
                del self.moves[left.get_name()]

        def check_reference(left, right):

            # Checks if an object is being referenced by more than one mutable object
            if left.type.is_mutable:
                for previous_reference in self.references.get(right.get_name(), []):
                    obj = previous_reference["obj"]
                    if obj.type.is_mutable:
                        msg = (obj.pos, "mutable object '{previous}' already references the same object".
                               format(previous=obj.name))
                        msg2 = (left.pos, "which you are trying to reference using the mutable object '{current}'".
                                format(current=left.name))
                        hints = ["Consider remove the mutability of one of them or both."]
                        raise util.Error([msg, msg2], hints=hints)

            # Add the left object as being more one reference to the right object
            self.references.setdefault(right.get_name(), [])
            self.references[right.get_name()].append({"obj": left,
                                                      "reference_assign": node,
                                                      "blocking_assign": None})

            # Check if a value which goes out of scope is referenced by an object
            # Obviously, this is only valid for local variables, not attributes
            if left.get_name() in self.definitions and right.get_name() in self.definitions:
                value_indent_level, value = self.definitions[right.get_name()]
                var_indent_level, left = self.definitions[left.get_name()]
                if value_indent_level > var_indent_level:
                    msg = (left.pos, "object '{left}' defined in outer scope".format(left=left.name))
                    msg2 = (right.pos, "cannot reference object '{right}' defined in inner scope".format(right=value.name))
                    hints = ["Consider move value '{right}' to same scope or outer scope"
                             " than '{left}' (or the contrary).".format(left=left.name, right=value.name)]
                    raise util.Error([msg, msg2], hints=hints)

        self.visit(node.right)
        self.check_move_or_copy(node.right, node.left.type)

        # Check every element of the tuple
        if isinstance(node.left, ast.Tuple):
            for i, element in enumerate(node.left.elements):
                check_object_blockings(element)

        # Check the single variable, class's attribute or list's item
        else:
            # Add hidden variables to function's scope
            if isinstance(node.left, ast.Symbol) and node.left.is_hidden():
                self.define_variable(node.left)

            check_object_blockings(node.left)
            if isinstance(node.right, ast.Reference):
                check_reference(node.left, node.right.value)

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
        self.moves[node.obj.get_name()] = node.obj

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
