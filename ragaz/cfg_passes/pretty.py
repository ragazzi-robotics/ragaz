"""
This pass is nothing short of a pretty printer.

Since LLVM output file could have details that would make it difficult to read, we use this processor to converter
this CFG to a simplified version of the output.

This processor can be invoked if you use the parameter 'show' in the command line.
"""

from ragaz import types_ as types

PASS_NAME = __name__.split(".")[-1]


class Prettifier(object):

    def __init__(self, module):
        self.module = module
        self.pretty_ir = None

    def process(self):
        self.pretty_ir = []

        for fn in self.module.functions:
            self.visit_function(fn)

        return self.pretty_ir

    def annotation(self, node):
        if node.type is not None:
            typ = self.visit(node.type)
            if getattr(node, "must_escape", False):
                typ += ":E"
            return " [{type}]".format(type=typ)
        else:
            return ""

    def visit(self, node):
        """
        This is used for call the proper visit method for a node. If node, for instance, is an ast.String, then
        this method will call `visit_string` method to handle the node properly.
        """
        if isinstance(node, types.Base):
            return self.visit_type(node)
        else:
            fn_name = "visit_" + str(node.__class__.__name__).lower()
            visit_node_fn = getattr(self, fn_name)
            return visit_node_fn(node)

    def visit_function(self, fn):
        if types.is_concrete(fn):
            if fn.self_type is not None:
                name = fn.self_type.name + "." + fn.name
            else:
                name = fn.name
            formals = ", ".join(self.visit(node) for node in fn.args)
            ret_type = fn.type.over["ret"]
            if ret_type is not None:
                ret = " -> {ret_type}".format(ret_type=self.visit_type(ret_type))
            else:
                ret = ""
            signature = "def {name}({formals}){ret}".format(name=name, formals=formals, ret=ret)

            suite = ""
            for block in sorted(fn.flow.blocks, key=lambda blk: blk.id):
                suite += "  {block_id:2}: # {block}\n".format(block_id=block.id, block=block.annotation)

                # As some helper nodes (like BeginScope and EndScope) won't be printed, we can't
                # trust on steps' ID. We must have a numbering only for Prettifier.
                step_id = 0

                for step in sorted(block.steps, key=lambda stp: stp.id):
                    step_text = self.visit(step)
                    if step_text != "":
                        suite += " {step_id} {step}\n".format(step_id="{" + "{step_id:02}".format(step_id=step_id) + "}",
                                                              step=step_text)
                        step_id += 1

            self.pretty_ir.append("{signature}:\n{suite}".format(signature=signature, suite=suite))

    def visit_beginscope(self, node):
        return ""

    def visit_endscope(self, node):
        return ""

    def unary_op(self, op, node):
        return "{op} {value}".format(op=op, value=self.visit(node.value))

    def binary_op(self, op, node):
        return "{op} {left} {right}".format(op=op, left=self.visit(node.left), right=self.visit(node.right))

    # Basic types

    def visit_noneval(self, node):
        return "NoneVal{annotation}".format(annotation=self.annotation(node))

    def visit_bool(self, node):
        return "{bool}{annotation}".format(bool=node.literal, annotation=self.annotation(node))

    def visit_int(self, node):
        return "{int}{annotation}".format(int=node.literal, annotation=self.annotation(node))

    def visit_float(self, node):
        return "{float}{annotation}".format(float=node.literal, annotation=self.annotation(node))

    def visit_byte(self, node):
        return "'{byte}'{annotation}".format(byte=chr(node.literal), annotation=self.annotation(node))

    # Structures

    def visit_array(self, node):
        return "Array({type}, {num_elements})".format(type=self.visit(node.target_type),
                                                      num_elements=self.visit(node.num_elements))

    def visit_string(self, node):
        return "{string}{annotation}".format(string=repr(node.literal), annotation=self.annotation(node))

    def visit_tuple(self, node):
        elements = ", ".join(self.visit(element) for element in node.elements)
        return "({elements})".format(elements=elements)

    def visit_list(self, node):
        elements = ", ".join(self.visit(element) for element in node.elements)
        return "[{elements}]".format(elements=elements)

    def visit_dict(self, node):
        def get_item(key, value):
            key = self.visit(key)
            value = self.visit(value)
            return key + ": " + value
        elements = ", ".join(get_item(key, value) for key, value in node.elements)
        return "{" + "{elements}".format(elements=elements) + "}"

    def visit_set(self, node):
        elements = ", ".join(self.visit(element) for element in node.elements)
        return "{" + "{elements}".format(elements=elements) + "}"

    def visit_attribute(self, node):
        return "{obj} . {attribute}{annotation}".format(obj=self.visit(node.obj), attribute=node.attribute,
                                                         annotation=self.annotation(node))

    def visit_setattribute(self, node):
        return self.visit_attribute(node)

    def visit_element(self, node):
        return "Element({obj}, {key}){annotation}".format(obj=self.visit(node.obj),
                                                          key=self.visit(node.key),
                                                          annotation=self.annotation(node))

    def visit_setelement(self, node):
        return self.visit_element(node)

    # Boolean operators

    def visit_not(self, node):
        return self.unary_op("Not", node)

    def visit_and(self, node):
        return self.binary_op("And", node)

    def visit_or(self, node):
        return self.binary_op("Or", node)

    # Comparison operators

    def visit_is(self, node):
        return self.binary_op("Is", node)

    def visit_equal(self, node):
        return self.binary_op("Equal", node)

    def visit_notequal(self, node):
        return self.binary_op("NotEqual", node)

    def visit_lowerthan(self, node):
        return self.binary_op("LowerThan", node)

    def visit_lowerequal(self, node):
        return self.binary_op("LowerEqual", node)

    def visit_greaterthan(self, node):
        return self.binary_op("GreaterThan", node)

    def visit_greaterequal(self, node):
        return self.binary_op("GreaterEqual", node)

    # Arithmetic operators

    def visit_neg(self, node):
        return self.unary_op("Neg", node)

    def visit_add(self, node):
        return self.binary_op("Add", node)

    def visit_sub(self, node):
        return self.binary_op("Sub", node)

    def visit_mod(self, node):
        return self.binary_op("Mod", node)

    def visit_mul(self, node):
        return self.binary_op("Mul", node)

    def visit_div(self, node):
        return self.binary_op("Div", node)

    def visit_floordiv(self, node):
        return self.binary_op("FloorDiv", node)

    def visit_pow(self, node):
        return self.binary_op("Pow", node)

    # Bitwise operators

    def visit_bwnot(self, node):
        return self.unary_op("BwNot", node)

    def visit_bwand(self, node):
        return self.binary_op("BwAnd", node)

    def visit_bwor(self, node):
        return self.binary_op("BwOr", node)

    def visit_bwxor(self, node):
        return self.binary_op("BwXor", node)

    def visit_bwshiftleft(self, node):
        return self.binary_op("BwShiftLeft", node)

    def visit_bwshiftright(self, node):
        return self.binary_op("BwShiftRight", node)

    # Control flow

    def visit_pass(self, node):
        return "Pass"

    def visit_branch(self, node):
        return "Branch {target_block}".format(target_block=node.target_block.id)

    def visit_condbranch(self, node):
        return "CondBranch {cond} ? {is_true_block} : {is_false_block}".format(cond=self.visit(node.cond),
                                                                               is_true_block=node.is_true_block.id,
                                                                               is_false_block=node.is_false_block.id)

    def visit_phi(self, node):
        return "Phi {left_id}:{left}, {right_id}:{right}".format(left_id=node.left[0].id,
                                                                 left=self.visit(node.left[1]),
                                                                 right_id=node.right[0].id,
                                                                 right=self.visit(node.right[1]))

    def visit_raise(self, node):
        return "Raise {value}".format(value=self.visit(node.value))

    def visit_landingpad(self, node):
        var = node.var
        map = ""
        for node, catch_block in node.map.items():
            map += self.visit(node)
            map += ": " + str(catch_block.id)
        return "LandingPad: {var} {map}".format(var=var, map="{" + map + "}")

    def visit_resume(self, node):
        return "Resume: {var}".format(var=node.var)

    def visit_call(self, node):
        args = ", ".join(self.visit(arg) for arg in node.args)
        if node.call_branch is not None:
            call_branch = " => {normal_block}, {exception_block}".format(
                normal_block=node.call_branch["normal_block"].id,
                exception_block=node.call_branch["exception_block"].id)
        else:
            call_branch = ""
        return "{callable}({args}){annotation}{call_branch}".format(callable=self.visit(node.callable), args=args,
                                                                     annotation=self.annotation(node),
                                                                     call_branch=call_branch)

    def visit_yield(self, node):
        return "Yield {value}".format(value=self.visit(node.value))

    def visit_return(self, node):
        if node.value is not None:
            return "Return {value}".format(value=self.visit(node.value))
        else:
            return "Return"

    # Symbols

    def visit_symbol(self, node):
        return "{symbol}{annotation}".format(symbol=node.get_name(), annotation=self.annotation(node))

    def visit_argument(self, node):
        return "{argument}{annotation}".format(argument=node.get_name(), annotation=self.annotation(node))

    def visit_namedarg(self, node):
        self.visit(node.value)

    def visit_variabledeclaration(self, node):
        return "Alloca {variables}".format(variables=self.visit(node.variables))

    def visit_assign(self, node):
        return "{left} = {right}".format(left=self.visit(node.left), right=self.visit(node.right))

    # Types

    def visit_as(self, node):
        return "As {left} {right}".format(left=self.visit(node.left), right=self.visit(node.type))

    def visit_isinstance(self, node):
        types = ", ".join(self.visit(typ) for typ in node.types)
        return "IsInstance({obj}, {types})".format(obj=self.visit(node.obj), types=types)

    def visit_sizeof(self, node):
        return "SizeOf({type})".format(type=self.visit(node.target_type))

    def visit_transmute(self, node):
        return "Transmute({obj}, {type})".format(obj=self.visit(node.obj), type=self.visit(node.type))

    def visit_type(self, node):
        if types.is_heap_owner(node):
            name = "$" + node.name
        else:
            name = node.name
        return name

    # Memory manipulation

    def visit_init(self, node):
        return "Init {type}".format(type=self.visit(node.type))

    def visit_del(self, node):
        return "Del {obj}".format(obj=self.visit(node.obj))

    def visit_reallocmemory(self, node):
        return "{obj}.Resize({num_elements})".format(obj=self.visit(node.obj),
                                                     num_elements=self.visit(node.num_elements))

    def visit_copymemory(self, node):
        return "CopyMemory({src}, {dst}, {num_elements})".format(src=self.visit(node.src),
                                                                 dst=self.visit(node.dst),
                                                                 num_elements=self.visit(node.num_elements))

    def visit_movememory(self, node):
        return "MoveMemory({src}, {dst}, {num_elements})".format(src=self.visit(node.src),
                                                                 dst=self.visit(node.dst),
                                                                 num_elements=self.visit(node.num_elements))

    def visit_reference(self, node):
        return "Ref {value}".format(value=self.visit(node.value))

    def visit_dereference(self, node):
        return "Deref {value}".format(value=self.visit(node.value))

    def visit_offset(self, node):
        return "Offset({obj}, {idx}){annotation}".format(obj=self.visit(node.obj), idx=self.visit(node.idx),
                                                          annotation=self.annotation(node))
