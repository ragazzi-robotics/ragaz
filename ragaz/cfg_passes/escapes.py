"""
This pass marks objects that will escape the function.

Every time a function is called, a portion of stack memory is reserved for this call and then as soon it is finished
the same portion is freed. So every variable created in the function is freed after call. However, many times the
content of an object must escape from this cleaning because it will be used later in the next instructions. To
solve this, it must be saved allocating it in the heap memory rather stack memory, and before the returning of the
function, its content be referenced by an object outside the function.

An example of object (that is in the heap memory) which must escapes are those strings passed as return of the
function:

    def return_owner() -> str
        var a = "I will survive"
        return a
    var b = return_owner()

Note in the example, that if 'a's content is freed in the return, then 'b' will reference an empty value. Thus,
the ownership of 'I will survive' must be moved to 'b' before the returning of the function. When 'a' be freed, it won't
clean the 'I will survive' string because it is not its owner anymore.

The same could be applied whether the value of 'a' was moved to an outside object before the returning.

More an example to explain this:

    def return_owner() -> str
        var a = "I will survive"
        var a2 = "Will I die?"
        return a
    var b = return_owner()

As mentioned earlier, 'I will survive' won't fred because it must escape (it is returned by the function) but this is
not the case for 'Will I die?' because it is not returned by any variable of the function neither has been owned by
an outside variable. So, yes, it will be fred in the heap.
"""

from ragaz import ast_ as ast, types_ as types
from ragaz.ast_passes import flow

PASS_NAME = __name__.split(".")[-1]


class EscapesAnalyser(object):

    def __init__(self, module):
        self.module = module
        self.fn = None
        self.escaping_objects = None

    def process(self):

        for fn in self.module.functions:
            self.visit_function(fn)

    def visit(self, node, mark_as_escaping=False):
        """
        This is used for call the proper visit method for a node. If node, for instance, is an ast.String, then
        this method will call `visit_string` method to handle the node properly.
        """
        fn_name = "visit_" + str(node.__class__.__name__).lower()
        visit_node_fn = getattr(self, fn_name)
        return visit_node_fn(node, mark_as_escaping)

    def check_must_escape(self, node, mark_as_escaping):
        if mark_as_escaping:
            node.must_escape = True
        node.type.is_heap_owner = node.must_escape

    # Node visitation methods

    def visit_function(self, fn):
        """
        Start the analysis.
        """
        if PASS_NAME not in fn.passes and types.is_concrete(fn):
            self.fn = fn
            self.escaping_objects = set()

            # Mark 'self' as escaping object if it's a class method
            if fn.self_type is not None:
                self.escaping_objects.add("self")

            for block in sorted(self.fn.flow.blocks, key=lambda blk: blk.id, reverse=True):
                for step in sorted(block.steps, key=lambda stp: stp.id, reverse=True):
                    self.visit(step)

            for arg in fn.args:
                arg.must_escape = arg.get_name() in self.escaping_objects

        fn.passes.append(PASS_NAME)

    def visit_beginscope(self, node, mark_as_escaping=False):
        pass

    def visit_endscope(self, node, mark_as_escaping=False):
        pass

    # Basic types

    def visit_noneval(self, node, mark_as_escaping=False):
        pass

    def visit_bool(self, node, mark_as_escaping=False):
        pass

    def visit_int(self, node, mark_as_escaping=False):
        pass

    def visit_float(self, node, mark_as_escaping=False):
        pass

    def visit_byte(self, node, mark_as_escaping=False):
        pass

    # Structures

    def visit_array(self, node, mark_as_escaping=False):
        self.visit(node.num_elements, mark_as_escaping)
        self.check_must_escape(node, mark_as_escaping)

    def visit_string(self, node, mark_as_escaping=False):
        self.check_must_escape(node, mark_as_escaping)

    def visit_tuple(self, node, mark_as_escaping=False):
        for element in node.elements:
            self.visit(element, True)
        self.check_must_escape(node, mark_as_escaping)

    def visit_list(self, node, mark_as_escaping=False):
        for element in node.elements:
            self.visit(element, True)
        self.check_must_escape(node, mark_as_escaping)

    def visit_dict(self, node, mark_as_escaping=False):
        for key, value in node.elements.items():
            self.visit(key, True)
            self.visit(value, True)
        self.check_must_escape(node, mark_as_escaping)

    def visit_set(self, node, mark_as_escaping=False):
        for element in node.elements:
            self.visit(element, True)
        self.check_must_escape(node, mark_as_escaping)

    def visit_attribute(self, node, mark_as_escaping=False):
        self.visit(node.obj, mark_as_escaping)

    def visit_setattribute(self, node, mark_as_escaping=False):
        self.visit_attribute(node, mark_as_escaping)

    def visit_element(self, node, mark_as_escaping=False):
        self.visit(node.obj, mark_as_escaping)

    def visit_setelement(self, node, mark_as_escaping=False):
        self.visit_element(node, mark_as_escaping)

    # Boolean operators

    def visit_not(self, node, mark_as_escaping=False):
        self.visit(node.value, mark_as_escaping)

    def boolean(self, node, mark_as_escaping=False):
        self.visit(node.left, mark_as_escaping)
        self.visit(node.right, mark_as_escaping)

    def visit_and(self, node, mark_as_escaping=False):
        self.boolean(node, mark_as_escaping)

    def visit_or(self, node, mark_as_escaping=False):
        self.boolean(node, mark_as_escaping)

    # Comparison operators

    def visit_is(self, node, mark_as_escaping=False):
        self.visit(node.left, mark_as_escaping)

    def compare(self, node, mark_as_escaping=False):
        self.visit(node.left, mark_as_escaping)
        self.visit(node.right, mark_as_escaping)

    def visit_equal(self, node, mark_as_escaping=False):
        self.compare(node, mark_as_escaping)

    def visit_notequal(self, node, mark_as_escaping=False):
        self.compare(node, mark_as_escaping)

    def visit_lowerthan(self, node, mark_as_escaping=False):
        self.compare(node, mark_as_escaping)

    def visit_lowerequal(self, node, mark_as_escaping=False):
        self.compare(node, mark_as_escaping)

    def visit_greaterthan(self, node, mark_as_escaping=False):
        self.compare(node, mark_as_escaping)

    def visit_greaterequal(self, node, mark_as_escaping=False):
        self.compare(node, mark_as_escaping)

    # Arithmetic operators

    def arith(self, node, mark_as_escaping=False):
        self.visit(node.left, mark_as_escaping)
        self.visit(node.right, mark_as_escaping)

    def visit_neg(self, node, mark_as_escaping=False):
        self.visit(node.value, mark_as_escaping)

    def visit_add(self, node, mark_as_escaping=False):
        self.arith(node, mark_as_escaping)

    def visit_sub(self, node, mark_as_escaping=False):
        self.arith(node, mark_as_escaping)

    def visit_mod(self, node, mark_as_escaping=False):
        self.arith(node, mark_as_escaping)

    def visit_mul(self, node, mark_as_escaping=False):
        self.arith(node, mark_as_escaping)

    def visit_div(self, node, mark_as_escaping=False):
        self.arith(node, mark_as_escaping)

    def visit_floordiv(self, node, mark_as_escaping=False):
        self.arith(node, mark_as_escaping)

    def visit_pow(self, node, mark_as_escaping=False):
        self.arith(node, mark_as_escaping)

    # Bitwise operators

    def bitwise(self, node, mark_as_escaping=False):
        self.visit(node.left, mark_as_escaping)
        self.visit(node.right, mark_as_escaping)

    def visit_bwnot(self, node, mark_as_escaping=False):
        self.visit(node.value, mark_as_escaping)

    def visit_bwand(self, node, mark_as_escaping=False):
        self.bitwise(node, mark_as_escaping)

    def visit_bwor(self, node, mark_as_escaping=False):
        self.bitwise(node, mark_as_escaping)

    def visit_bwxor(self, node, mark_as_escaping=False):
        self.bitwise(node, mark_as_escaping)

    def visit_bwshiftleft(self, node, mark_as_escaping=False):
        self.bitwise(node, mark_as_escaping)

    def visit_bwshiftright(self, node, mark_as_escaping=False):
        self.bitwise(node, mark_as_escaping)

    # Control flow

    def visit_pass(self, node, mark_as_escaping=False):
        pass

    def visit_branch(self, node, mark_as_escaping=False):
        pass

    def visit_condbranch(self, node, mark_as_escaping=False):
        pass

    def visit_phi(self, node, mark_as_escaping=False):
        self.visit(node.left[1], mark_as_escaping)
        self.visit(node.right[1], mark_as_escaping)

    def visit_raise(self, node, mark_as_escaping=False):
        self.visit(node.value, True)

    def visit_landingpad(self, node, mark_as_escaping=False):
        pass

    def visit_resume(self, node, mark_as_escaping=False):
        pass

    def visit_call(self, node, mark_as_escaping=False):
        is_method = isinstance(node.fn, ast.Function)

        if is_method and (node.fn.name == "__free__" or self.fn.name == "__del__"):
            return

        for i, arg_type in enumerate(node.fn.type.over["args"]):
            if types.is_heap_owner(arg_type):
                self.visit(node.args[i], True)
            else:
                self.visit(node.args[i], mark_as_escaping)

        if is_method and node.fn.name == "__init__":
            # Mark 'self' as escaping object
            self.visit(node.args[0], mark_as_escaping)

    def visit_yield(self, node, mark_as_escaping=False):
        self.visit_return(node, mark_as_escaping)

    def visit_return(self, node, mark_as_escaping=False):
        if node.value is not None:
            self.visit(node.value, True)

    # Symbols

    def visit_symbol(self, node, mark_as_escaping=False):
        if mark_as_escaping:
            # From this point until its definition, this variable will be tracked as escaping object . This will
            # be useful to check whether any variable assigned to an escaping object also is an escaping object.
            self.escaping_objects.add(node.get_name())

        # If the object was marked to escape in this or in other visit, keep it as escaping
        node.must_escape = node.get_name() in self.escaping_objects

        # Mark the pointer object which escapes as being a heap owner
        if node.must_escape:
            node.type = types.check_heap_ownership(node.type)

    def visit_namedarg(self, node, mark_as_escaping=False):
        self.visit(node.value, mark_as_escaping)

    def visit_variabledeclaration(self, node, mark_as_escaping=False):
        if isinstance(node.variables, ast.Tuple):
            for element in node.variables.elements:
                self.visit(element)
        elif isinstance(node.variables, ast.Symbol):
            self.visit(node.variables)

    def visit_assign(self, node, mark_as_escaping=False):

        # Check whether any variable assigned to an escaping object also is an escaping object
        if isinstance(node.left, ast.Tuple):
            tracked = []
            for element in node.left.elements:
                self.visit(element)
                tracked.append(element.must_escape)
            mark_as_escaping = any(tracked)
            self.visit(node.right, mark_as_escaping)
        elif isinstance(node.left, ast.Symbol):
            self.visit(node.left)
            self.visit(node.right, node.left.must_escape)
        elif isinstance(node.left, (flow.SetAttribute, flow.SetElement)):
            self.visit(node.left, True)
            self.visit(node.right, True)

    # Types

    def visit_as(self, node, mark_as_escaping=False):
        self.visit(node.left, mark_as_escaping)

    def visit_isinstance(self, node, mark_as_escaping=False):
        pass

    def visit_sizeof(self, node, mark_as_escaping=False):
        pass

    def visit_transmute(self, node, mark_as_escaping=False):
        self.visit(node.obj, mark_as_escaping)

    # Memory manipulation

    def visit_init(self, node, mark_as_escaping=False):
        self.check_must_escape(node, mark_as_escaping)

    def visit_del(self, node, mark_as_escaping=False):
        self.visit(node.obj, False)

    def visit_reallocmemory(self, node, mark_as_escaping=False):
        self.visit(node.obj, mark_as_escaping)
        self.visit(node.num_elements, mark_as_escaping)

    def visit_copymemory(self, node, mark_as_escaping=False):
        self.visit(node.src, mark_as_escaping)
        self.visit(node.dst, mark_as_escaping)
        self.visit(node.num_elements, mark_as_escaping)

    def visit_movememory(self, node, mark_as_escaping=False):
        self.visit(node.src, mark_as_escaping)
        self.visit(node.dst, mark_as_escaping)
        self.visit(node.num_elements, mark_as_escaping)

    def visit_reference(self, node, mark_as_escaping=False):
        self.visit(node.value, mark_as_escaping)

    def visit_dereference(self, node, mark_as_escaping=False):
        self.visit(node.value, mark_as_escaping)

    def visit_offset(self, node, mark_as_escaping=False):
        self.visit(node.obj, mark_as_escaping)
