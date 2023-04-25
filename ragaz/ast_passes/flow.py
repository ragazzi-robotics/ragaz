"""
This pass converts an AST (abstract syntax tree) into a CFG (control-flow graph).

This is essential once that LLVM (and machine language) generated code is structured in a CFG flow.

This job involves create a flow of execution where once the set of instructions of a block is done, the execution
will be headed to another block though 'branch' or 'cbranch' (conditional branch) jump instructions.

Look the piece of code bellow:

    if b * (3 + c / 2) > 0:
        print("greater than")
    else:
        print("less than")

The AST for it is something like that:

     __________________________ IF ____________________
     |                           |                    |
     |                          GT                    |
     |                         /  \                   |
 if_body:                    MUL   0              else_body:
   PRINT("Greater than")    /  \                     PRINT("Less than")
                           b   ADD
                               /  \
                              3   DIV
                                  / \
                                 c   2

This pass recursively deconstructs the nested expressions above into something like that:

if_cond:
    $1 = DIV c, 2
    $2 = ADD 3, $1
    $3 = MUL b, $2
    $4 = GREATER_THAN $3, 0
    COND_BRANCH $4, if_body, else_body
if_body:
    PRINT("Greater than")
    BRANCH end
else_body:
    PRINT("Less than")
    BRANCH end
end:
    (next instructions)

Note that the nested expressions are stored into temporary variables and the flow control is done by
jumping instructions ('branch' or 'conditional branch') which head the execution to another block ('if_body',
'else_body', or'end' in the example). Note that every block must have at least one instruction and this
last instruction must be a jumping instruction.

To you understand better the code we recommend you start your reading from 'visit_function' and so on.
"""

from ragaz import ast_ as ast, util

PASS_NAME = __name__.split(".")[-1]


class SetAttribute(ast.Attribute):
    pass


class SetElement(ast.Element):
    pass


class Branch(util.Repr):

    def __init__(self, target_block):
        self.target_block = target_block


class CondBranch(util.Repr):

    def __init__(self, cond, is_true_block, is_false_block):
        self.cond = cond
        self.is_true_block = is_true_block
        self.is_false_block = is_false_block


class Phi(util.Repr):

    def __init__(self, pos, left, right):
        self.pos = pos
        self.left = left
        self.right = right
        self.type = None


class LandingPad(util.Repr):

    def __init__(self, var, map, fail_block):
        self.var = var
        self.map = map
        self.fail_block = fail_block


class Resume(util.Repr):

    def __init__(self, var):
        self.var = var


class BeginScope(util.Repr):
    pass


class EndScope(util.Repr):
    pass


FINAL = (ast.Return, ast.Raise, ast.Yield, Branch, CondBranch, LandingPad, Resume)


class Block(util.Repr):

    def __init__(self, id, annotation):
        self.id = id
        self.annotation = annotation
        self.steps = []
        self.ir = None

    def push_step(self, node):
        node.id = len(self.steps)
        self.steps.append(node)

    def insert_step(self, previous_node, node):
        idx = self.steps.index(previous_node)

        # Never include any instruction after a redirection (branch, return, etc)
        if isinstance(previous_node, EndScope) and len(self.steps) > 1 and isinstance(self.steps[idx - 1], FINAL):
            idx -= 1

        self.steps.insert(idx, node)
        for id, step in enumerate(self.steps):
            step.id = id

    def last_step(self):
        # Once end EndScope is not a valid step but a helper, this function returns the last valid step
        for step in sorted(self.steps, key=lambda stp: stp.id, reverse=True):
            if not isinstance(step, EndScope):
                return step
        return None

    def need_branch(self):
        """
        Every block needs to redirect the flow to other target block. If the block doesn't have a final instruction, ie.
        return, branch, conditional, etc., or even if it has zero instructions then this function will inform that it
        is incomplete and needs a branch.
        """
        last_step = self.last_step()
        return len(self.steps) == 0 or not (isinstance(last_step, FINAL) or
                                            (isinstance(last_step, ast.Call) and last_step.call_branch is not None))


class Flow(util.Repr):
    """
    The ``Flow`` object represents a directed graph of ``Block`` objects, which will end up as a basic block
    in LLVM IR.
    """

    def __init__(self):
        self.blocks = []
        self.yields = {}

    def create_block(self, annotation):
        id = len(self.blocks)
        block = Block(id, annotation)
        self.blocks.append(block)
        return block

    def remove_block(self, block):
        self.blocks.remove(block)


ATOMIC = ast.NoneVal, ast.Byte, ast.Bool, ast.Int, ast.Float, ast.Symbol, ast.Attribute, ast.Element


class FlowFinder(object):
    """
    This class constructs flow graphs, which is structured as a syntax tree walking class.
    The important functionality here is the deconstruction of nested expressions into temporary variables (see the
    ``deconstruct()`` method) and the transformation of the various source-level flow control features into a control
    flow graph of basic blocks.
    """

    def __init__(self, module):
        self.module = module
        self.fn = None
        self.curr_block = None
        self.curr_loop = None
        self.curr_try = None
        self.potential_raiser_calls = None

    def process(self):

        # Constructs ``Flow`` objects for this function node which represents a directed graph of ``Block``
        # objects and their found flow, which will end up as a basic block in LLVM IR
        for fn in self.module.functions:
            self.visit_function(fn)

    def deconstruct(self, node):
        """
        Recursively deconstructs nested expressions into temporary variables.
        As example, the expression bellow:

            a = b * (3 + c / 2)

        is deconstructed as:

            $1 = div(c, 2)
            $2 = add(3, $1)
            $3 = mul(b, $2)
            a = $3

        This is necessary because LLVM and consequently machine processors work this way.
        """

        # If node is atomic (byte, bool, integer, name, none, etc) then deconstruction is over
        # Otherwise recursively deconstructs the node until an atomic node be found
        if isinstance(node, ATOMIC):
            return self.visit(node)
        elif isinstance(node, ast.NamedArg):
            if isinstance(node.value, ATOMIC):
                return self.visit(node)
            else:
                node.value = self.deconstruct(node.value)
                return node

        # Create a temporary variable to store the value of this part of the expression
        name = "hidden" + self.fn.generate_suffix()
        left = ast.Symbol(node.pos, name=name, internal_name=name)
        right = self.visit(node)
        assignment = ast.Assign(None, left, right)
        self.curr_block.push_step(assignment)

        if isinstance(right, ast.Call):
            self.check_call(right)

        return left

    def check_move_or_copy(self, node, call=None):
        if isinstance(node, (ast.Symbol, ast.Attribute, ast.Tuple)):
            node.check_move = True
            node.copy_or_move_call = call
        elif isinstance(node, ast.Element):
            node.check_copy = True
            node.copy_or_move_call = call

    def check_call(self, node):
        """
        This function will check if the call is inside a `try` block, and if so add a call_branch to redirect the flow
        in case of exception found.
        """

        if self.curr_try is not None:

            # Create a `continuation` block and set it as destination from `call` block
            next_block = self.curr_block = \
                self.fn.flow.create_block("try-continue" + self.fn.generate_suffix())

            # After call is done the control is passed to `next` block
            node.call_branch = {"normal_block": next_block, "exception_block": None}

            # Append the call as potential exception raiser
            self.potential_raiser_calls[self.curr_try].append(node)

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
        util.check_previous_pass(self.module, fn, PASS_NAME)
        if PASS_NAME not in fn.passes:

            # Create a new flow object for the function node
            self.fn = fn
            self.fn.flow = Flow()

            # Set the first block as current
            entry_block = self.fn.flow.create_block("entry")
            self.curr_block = entry_block

            # Reset the potential raisers
            self.potential_raiser_calls = {}

            # Visit all steps for find the flow
            self.visit_suite(fn.suite)

            # Append a `void` return if there are no call branch or final branch as last step of the final branch
            # It must be before then `EndScope` node
            final_block = self.fn.flow.blocks[-1]
            if final_block.need_branch():
                end_scope = final_block.steps[-1]
                return_node = ast.Return(None, None)
                final_block.insert_step(end_scope, return_node)

        fn.passes.append(PASS_NAME)
        return fn

    def visit_suite(self, node):

        # Create a node to the beginning of every suite once it means the beginning of scope for variables created in
        # the suite
        begin_scope = BeginScope()
        self.curr_block.push_step(begin_scope)
        self.visit(begin_scope)

        for statement in node.statements:

            # Visit the current statement
            n = self.visit(statement)
            if n is not None:
                self.curr_block.push_step(n)
                if isinstance(n, ast.Call):
                    self.check_call(n)

        # Create a note to the end of every suite once it means the end of scope for variables created in the suite
        end_scope = EndScope()
        self.curr_block.push_step(end_scope)
        self.visit(end_scope)

    def visit_beginscope(self, node):
        return node

    def visit_endscope(self, node):
        return node

    def unary_op(self, node):
        node.value = self.deconstruct(node.value)
        return node

    def binary_op(self, node):
        node.left = self.deconstruct(node.left)
        node.right = self.deconstruct(node.right)
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
        node.num_elements = self.deconstruct(node.num_elements)
        return node

    def visit_string(self, node):
        return node

    def visit_tuple(self, node):
        for i, element in enumerate(node.elements):
            self.check_move_or_copy(element)
            node.elements[i] = self.deconstruct(element)
        return node

    def visit_list(self, node):
        for i, element in enumerate(node.elements):
            self.check_move_or_copy(element)
            node.elements[i] = self.deconstruct(element)
        return node

    def visit_dict(self, node):
        elements = {}
        for key, value in node.elements.items():
            self.check_move_or_copy(value)
            key = self.deconstruct(key)
            value = self.deconstruct(value)
            elements[key] = value
        node.elements = elements
        return node

    def visit_set(self, node):
        for i, element in enumerate(node.elements):
            self.check_move_or_copy(element)
            node.elements[i] = self.deconstruct(element)
        return node

    def visit_attribute(self, node):
        node.obj = self.deconstruct(node.obj)
        return node

    def visit_setattribute(self, node):
        return self.visit_attribute(node)

    def visit_element(self, node):
        node.obj = self.deconstruct(node.obj)
        node.key = self.deconstruct(node.key)
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
        self.curr_block.push_step(node)

    def visit_ternary(self, node):

        # Set the current block as entry block for the ternary flow
        entry_block = self.curr_block
        cond = self.deconstruct(node.cond)

        # Create left block of the ternary expression
        left_block = self.curr_block = self.fn.flow.create_block("ternary-left")
        left_var = self.deconstruct(node.values[0])

        # Create right block of the ternary expression
        right_block = self.curr_block = self.fn.flow.create_block("ternary-right")
        right_var = self.deconstruct(node.values[1])

        # Create a condition branch where the `left` block is the destination in case of condition be true and
        # `left` block when condition be false
        cond_branch = CondBranch(cond, left_block, right_block)
        entry_block.push_step(cond_branch)

        # Create an `exit` block and set it as destination from both `left` and `right` blocks
        exit_block = self.curr_block = self.fn.flow.create_block("ternary-exit")
        left_block.push_step(Branch(exit_block))
        right_block.push_step(Branch(exit_block))

        return Phi(node.pos, (left_block, left_var), (right_block, right_var))

    def visit_if(self, node):

        prevcond_block, exits = None, []
        for part in node.parts:
            cond = part["cond"]
            suite = part["suite"]

            if cond is not None:

                # Handles this part as IF because it have no previous condition
                if prevcond_block is None:

                    # Create a `suite` statements block
                    suite_block = self.fn.flow.create_block("if-suite")

                    # Create a condition branch where the `suite` statements block is the destination in case of
                    # condition be true and set it as destination from current block
                    self.curr_block.push_step(CondBranch(self.deconstruct(cond), suite_block, None))

                # Handles this part as ELIF because of it have previous condition
                else:

                    # Create a `condition` block
                    cond_block = self.curr_block = self.fn.flow.create_block("if-cond")

                    # Define this `condition` block as destination of the previous `if` or `elif` in case of its
                    # condition be false
                    prevcond_block.last_step().is_false_block = cond_block

                    # Create a `suite` statements block
                    suite_block = self.fn.flow.create_block("if-suite")

                    # Create a condition branch where the `suite` statements block is the destination in case of
                    # condition be true and set it as destination from current block
                    cond_block.push_step(CondBranch(self.deconstruct(cond), suite_block, None))

                prevcond_block = self.curr_block

            # Handles this part as ELIF because has no condition
            else:

                # Create a `suite` statements block
                suite_block = self.fn.flow.create_block("if-suite")

                # Define this `suite` statements block as destination of the previous `if` or `elif` in case of its
                # condition be false
                prevcond_block.last_step().is_false_block = suite_block
                prevcond_block = None

            self.curr_block = suite_block
            self.visit_suite(suite)
            if self.curr_block.need_branch():
                exits.append(self.curr_block)

        if prevcond_block is None and len(exits) == 0:
            return

        # Create an `exit` block
        exit_block = self.curr_block = self.fn.flow.create_block("if-exit")
        if prevcond_block is not None:

            # Define the `exit` block as destination of the previous `if` or `elif` in case of its
            # condition be false
            prevcond_block.last_step().is_false_block = exit_block

        # Set `exit` block as destination of all blocks without a branch
        for block in exits:
            if block.need_branch():
                block.push_step(Branch(exit_block))

    def visit_while(self, node):

        # Create a `cond` block and set it as destination from current block
        cond_block = self.fn.flow.create_block("while-cond")
        self.curr_block.push_step(Branch(cond_block))
        self.curr_block = cond_block

        # Create a `suite` block
        suite_block = self.fn.flow.create_block("while-suite")

        # Create a condition branch where the `suite` block is the destination in case of condition be true and set
        # the condition as destination from `cond` block
        cond_branch = CondBranch(self.deconstruct(node.cond), suite_block, None)
        cond_block.push_step(cond_branch)

        # Visit the suite of statements
        outter_loop = self.curr_loop
        self.curr_loop = node
        self.curr_block = suite_block
        self.visit_suite(node.suite)
        self.curr_loop = outter_loop

        # Set the `cond` block as destination from last block executed in the suite of statements
        # This is necessary because in every loop iteration the condition must be verified again
        self.curr_block.push_step(Branch(cond_block))

        # Create an `exit` block
        exit_block = self.curr_block = self.fn.flow.create_block("while-exit")

        # Define the `exit` block as destination from `cond` block in case of its condition be false
        cond_branch.is_false_block = exit_block

        # Define the destination of `continue` statement to `cond` block
        for n in node.loop_jumpers["continue"]:
            n.target_block = cond_block

        # Define the destination of `break` statement to `exit` block
        for n in node.loop_jumpers["break"]:
            n.target_block = exit_block

    def visit_break(self, node):
        branch = Branch(None)
        self.curr_block.push_step(branch)
        self.curr_loop.loop_jumpers["break"].append(branch)

    def visit_continue(self, node):
        branch = Branch(None)
        self.curr_block.push_step(branch)
        self.curr_loop.loop_jumpers["continue"].append(branch)

    def visit_raise(self, node):
        self.curr_block.push_step(node)
        self.check_call(node)

    def visit_tryblock(self, node):

        # Visit the suite of statements to create a list of potential raiser calls
        outter_try = self.curr_try
        self.curr_try = node
        calls = self.potential_raiser_calls[self.curr_try] = []
        self.visit_suite(node.suite)
        self.curr_try = outter_try

        # If there's a 'try-continue' block without a redirect to 'try-exit' block then hold it to
        # terminate it when 'try-exit' be created
        last_block_try = self.curr_block

        # Create a landing pad which is where the exceptions land, and corresponds to the code found in the catch
        # portion of a try/catch sequence
        internal_variable_name = self.fn.generate_suffix()
        landing_pad = LandingPad(internal_variable_name, None, None)
        resume = Resume(internal_variable_name)

        # Create a `landing pad` block
        landing_pad_block = self.fn.flow.create_block("landing-pad")
        landing_pad_block.push_step(landing_pad)

        # Create a map to store the `catch` block of each exception type that was explicitly handled by the developer
        map = {}
        for handler in node.catch:
            # Create a `catch` block for this handler
            catch_block = self.curr_block = self.fn.flow.create_block("catch")

            self.visit_suite(handler.suite)
            map[handler.type] = catch_block
        landing_pad.map = map

        # Create a `unmatched` block
        unmatched_block = self.fn.flow.create_block("caught-no-match")

        # Set `unmatched` block as the destination which is used when landing pad doesn't find any handle for an
        # exception raised
        landing_pad.fail_block = unmatched_block

        # Set the resume instruction as destination from `unmatched` block
        unmatched_block.push_step(resume)

        # Create an `exit` block
        exit_block = self.curr_block = self.fn.flow.create_block("try-exit")

        # Organize the flow: after call is done the control is passed to next step or then to landing pad
        # whether exception is raised.
        if len(calls) > 0:
            for i, call in enumerate(calls):
                call.call_branch["exception_block"] = landing_pad_block

        # Reorganize the flow redirecting the last block of the 'try' suite to the 'exit' block
        block_is_empty = len(last_block_try.steps) == 1 and type(last_block_try.steps[-1]) == EndScope
        if last_block_try.annotation.startswith("try-continue") and block_is_empty:
            calls[-1].call_branch["normal_block"] = exit_block
            self.fn.flow.remove_block(last_block_try)
        elif last_block_try.need_branch():
            end_scope = last_block_try.steps[-1]
            last_block_try.insert_step(end_scope, Branch(exit_block))

        # Set `exit` block as destination of all `catch` blocks and the `unmatched` block
        for caught_block in map.values():
            if caught_block.need_branch():
                caught_block.push_step(Branch(exit_block))

    def visit_call(self, node):
        node.callable = self.visit(node.callable)
        for i, arg in enumerate(node.args):
            self.check_move_or_copy(arg, node)
            node.args[i] = self.deconstruct(arg)
        return node

    def visit_yield(self, node):
        if node.value is not None:
            node.value = self.deconstruct(node.value)

        # Create a `yield` block and set it as destination from `current` block
        next_block = self.fn.flow.create_block("yield-to")
        self.curr_block.push_step(node)

        # Define this as one of the yields of the current block
        self.fn.flow.yields[self.curr_block] = next_block

        node.target_block = next_block
        self.curr_block = next_block

    def visit_return(self, node):
        if node.value is not None:
            node.value = self.deconstruct(node.value)
        self.curr_block.push_step(node)

    # Symbols

    def visit_symbol(self, node):
        return node

    def visit_namedarg(self, node):
        node.value = self.visit(node.value)
        return node

    def visit_variabledeclaration(self, node):
        self.curr_block.push_step(node)

        if node.assignment is not None:
            self.visit(node.assignment)

    def visit_assign(self, node):

        self.check_move_or_copy(node.right)
        node.right = self.visit(node.right)

        node.left = self.visit(node.left)
        if isinstance(node.left, ast.Attribute):
            node.left = SetAttribute(node.left.pos, node.left.obj, node.left.attribute)
        elif isinstance(node.left, ast.Element):
            node.left = SetElement(node.left.pos, node.left.obj, node.left.key)

        # When a call is assigned to variable inside a try-catch block, it must be split in two parts. This
        # is necessary because after call the execution goes to a next block or landing pad block and so the
        # instruction to store the call result to the variable is never executed.
        # Thus, first we call the function and store the result in a helper variable and later in the following
        # block we store the helper variable's value to actual variable
        must_split = isinstance(node.right, ast.Call) and self.curr_try is not None
        if must_split:
            name = "hidden" + self.fn.generate_suffix()
            return_var = ast.Symbol(None, name, internal_name=name)
            left = node.left
            node = ast.Assign(None, return_var, node.right)

        self.curr_block.push_step(node)

        # Now we store the value from helper variable to the actual variable
        if must_split:
            self.check_call(node.right)
            var_assignment = ast.Assign(None, left, return_var)
            self.curr_block.push_step(var_assignment)

    # Types

    def visit_as(self, node):
        node.left = self.deconstruct(node.left)
        return node

    def visit_isinstance(self, node):
        node.obj = self.deconstruct(node.obj)
        return node

    def visit_sizeof(self, node):
        return node

    def visit_transmute(self, node):
        node.obj = self.deconstruct(node.obj)
        return node

    # Memory manipulation

    def visit_del(self, node):
        node.obj = self.deconstruct(node.obj)
        return node

    def visit_reallocmemory(self, node):
        node.obj = self.deconstruct(node.obj)
        node.num_elements = self.deconstruct(node.num_elements)
        return node

    def visit_copymemory(self, node):
        node.src = self.deconstruct(node.src)
        node.dst = self.deconstruct(node.dst)
        node.num_elements = self.deconstruct(node.num_elements)
        return node

    def visit_movememory(self, node):
        node.src = self.deconstruct(node.src)
        node.dst = self.deconstruct(node.dst)
        node.num_elements = self.deconstruct(node.num_elements)
        return node

    def visit_reference(self, node):
        return self.unary_op(node)

    def visit_dereference(self, node):
        return self.unary_op(node)

    def visit_offset(self, node):
        node.obj = self.deconstruct(node.obj)
        node.idx = self.deconstruct(node.idx)
        return node
