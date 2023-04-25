"""
This pass evaluates the literal expressions in order to check dead code and perform other optimizations.

In the example:
    a = 1 + 1

we could simply evaluate the expression and reduce the number of processor steps replacing it to
    a = 2

In this other example, the expression is always 'True' and thus the 'else' suite never is executed:

    if 1 + 1 == 2:
        (always is executed)
    else:
        (never is executed thus can be removed)

this generates dead code which could decrease the runtime speed (because an unnecessary condition checking) and
increase the size of the executed file.
"""

from ragaz import ast_ as ast, util

PASS_NAME = __name__.split(".")[-1]
JUMPER = (ast.Return, ast.Raise, ast.Break, ast.Continue, ast.Pass)


class ExpressionsEvaluator(object):

    def __init__(self, module):
        self.module = module
        self.fn = None

    def process(self):

        # Traverse the AST (abstract syntax tree) of the functions and remove any dead code found.
        for fn in self.module.functions:
            self.visit_function(fn)

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

            # Visit all steps for find the dead code
            fn.suite = self.visit(fn.suite)

        fn.passes.append(PASS_NAME)
        return fn

    def visit_suite(self, node):

        last_statement, last_step = None, None
        updated_statements = []
        for statement in node.statements:

            # Here we ignore any statements after a `return`, `break`, etc, once they become unreachable (dead code)
            if isinstance(last_statement, JUMPER):
                msg = (last_statement.pos, "this instruction generates dead code")
                hints = ["Remove the instructions just bellow it once they will never be executed."]
                util.warn([msg], hints)
                break

            # Visit the current statement
            statement = self.visit(statement)
            if statement is not None:
                updated_statements.append(statement)

            last_statement = statement

        node.statements = updated_statements
        return node

    def unary_op(self, node):
        node.value = self.visit(node.value)
        if node.value.is_literal:
            try:
                node.literal = eval("{op} {value}".format(op=node.op, value=node.value.literal))
            except:
                node.is_literal = False
            finally:
                node.is_literal = True
        return node

    def binary_op(self, node):
        node.left = self.visit(node.left)
        node.right = self.visit(node.right)
        if node.left.is_literal and node.right.is_literal:
            try:
                node.literal = eval("{left} {op} {right}".format(left=node.left.literal,
                                                                 op=node.op,
                                                                 right=node.right.literal))
            except:
                node.is_literal = False
            finally:
                node.is_literal = True
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
        return self.binary_op(node)

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

        # Evaluate if the condition is literal and if the same is true or false. The part which is always true
        # will be returned as result of the expression while the other one will be ignored once it will generate
        # unreachable (dead) code like in:
        #
        #   a = "x" if 1 else "y"  ('a' never will be 'y')
        if node.cond.is_literal:
            if node.cond.literal:
                return node.values[0]
            else:
                return node.values[1]

        return node

    def visit_if(self, node):
        for part in node.parts:
            if part["cond"] is not None:
                part["cond"] = self.visit(part["cond"])
            part["suite"] = self.visit(part["suite"])

        # Evaluate if the condition is literal and if the same is true or false. The part which is always false
        # will be removed once it will generate unreachable (dead) code like in:
        #
        #   if 0:
        #      (dead code)
        #   elif 1:
        #      (some stuff)
        #   else:
        #      (dead code)
        parts_to_remove = []
        for i, part in enumerate(node.parts):
            cond = part["cond"]
            if cond is not None:
                if cond.is_literal:
                    if cond.literal:
                        # Remove all parts after this one once they never will execute
                        parts_to_remove.extend(node.parts[i+1:])
                        break
                    else:
                        # Remove this part once it never will execute
                        parts_to_remove.append(part)
                        msg = (cond.pos, "this instruction generates dead code")
                        hints = ["Remove this 'if/elif' statement once its instructions will never be executed."]
                        util.warn([msg], hints)
        while len(parts_to_remove) > 0:
            part = parts_to_remove.pop()
            node.parts.remove(part)

        return node

    def visit_while(self, node):
        node.cond = self.visit(node.cond)
        node.suite = self.visit(node.suite)

        # Evaluate if the condition is literal and if the same is false. If so just ignore the statement once it would
        # generate unreachable (dead) code like in:
        #
        #   while 0:
        #      (dead code)
        if node.cond.is_literal and not node.cond.literal:
            msg = (node.cond.pos, "this instruction generates dead code")
            hints = ["Remove this 'while' statement once its instructions will never be executed."]
            util.warn([msg], hints)
            return None

        return node

    def visit_for(self, node):
        node.source = self.visit(node.source)
        node.suite = self.visit(node.suite)
        return node

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
        for i, arg in enumerate(node.args):
            node.args[i] = self.visit(arg)
        return node

    def visit_yield(self, node):
        if node.value is not None:
            node.value = self.visit(node.value)
        self.fn.is_generator = True
        return node

    def visit_return(self, node):
        if node.value is not None:
            node.value = self.visit(node.value)
        return node

    # Symbols

    def visit_symbol(self, node):
        return node

    def visit_namedarg(self, node):
        node.value = self.visit(node.value)
        return node

    def visit_variabledeclaration(self, node):
        if node.assignment is not None:
            node.assignment = self.visit(node.assignment)
        return node

    def visit_assign(self, node):
        node.right = self.visit(node.right)
        return node

    def visit_inplace(self, node):
        node.operation.right = self.visit(node.operation.right)
        return node

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
