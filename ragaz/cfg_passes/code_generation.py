"""
This pass generates IR code from CFG (control-flow graph), which will be compiled by the LLVM compiler generating
a binary file.

First all, it traverses all classes stored in symbols table to generate IR code for the declaration of
global variables, functions signatures, etc, and also traverses all types stored in types table to generate IR code
for the declaration of the types used in the module,

Finally, it walks the CFG of every function to generate IR code for each block and its set of instructions.

This code generation is intermediate by a nice library named 'llvmlite', which you mount the instructions using
its API to create blocks, load/store values, jumpers like 'branch', 'cbranch', etc., and after all done you generate
the IR code into a single string.

All the 'visit_*()' methods will return a ``Value`` object, which contains the Ragaz type and the IR instance for
the object processed.
"""

import copy
import llvmlite.binding as llvm
from collections import OrderedDict
from llvmlite import ir
from ragaz import ast_ as ast, types_ as types, module as module_, util
from ragaz.ast_passes import flow
from ragaz.cfg_passes import typing

void = ir.VoidType()
i1 = ir.IntType(1)
i8 = ir.IntType(8)
i16 = ir.IntType(16)
i32 = ir.IntType(32)
i64 = ir.IntType(64)
integer = ir.IntType(32)
floating = ir.DoubleType()

LAST_OBJECT_ID = 0


class Value(util.Repr):

    def __init__(self, typ, ir):
        self.type = typ
        self.ir = ir
        if typ.ir != ir.type:
            assert False, str(typ.ir) + " != " + str(ir.type)


def generate_object_id():
    global LAST_OBJECT_ID
    LAST_OBJECT_ID += 1
    return LAST_OBJECT_ID


class CodeGenerator(object):

    def __init__(self, target_machine, word_size):
        self.target_machine = target_machine
        self.word_size = word_size
        self.word_size_ir = "i" + str(word_size)
        self.main = None
        self.module = None
        self.fn = None

        # Declare the default integer based on target's word size
        global integer
        integer = ir.IntType(word_size)

    def generate(self, module):

        # Create an IR object to the module
        module.ir = ir.Module(name=module.file)

        self.module = module
        self.process_module()

        return module.ir

    def visit(self, node):
        """
        This is used for call the proper visit method for a node. If node, for instance, is an ast.String, then
        this method will call `visit_string` method to handle the node properly.
        """
        fn_name = "visit_" + str(node.__class__.__name__).lower()
        visit_node_fn = getattr(self, fn_name)
        ret = visit_node_fn(node)
        return ret

    # Some type system helper methods

    def sizeof(self, typ):
        return typ.get_abi_size(self.target_machine.target_data, self.module.ir.context)

    def check_wrap(self, value, formal_type, arg):

        # If the formal type is a reference, then we create a pointer to the value if there's no pointer to it
        # TODO: Try remove the check for trait
        if types.is_reference(formal_type) and not types.is_wrapped(arg.type) and not isinstance(formal_type.over,
                                                                                                 types.Trait):
            value_addr = self.builder.alloca(value.type.ir)
            self.builder.store(value.ir, value_addr)
            return Value(types.Wrapper(value.type), value_addr)
        else:
            return value

    def coerce(self, src_value, dst_type, node=None):
        """
        Convert a value to a given type.
        """

        # Get the unwrapped source type
        unwrapped_src_type = src_value.type
        src_type_wrap_levels = 0
        while types.is_wrapped(unwrapped_src_type):
            unwrapped_src_type = unwrapped_src_type.over
            src_type_wrap_levels += 1

        # Get the unwrapped target type
        unwrapped_dst_type = dst_type
        dst_type_wrap_levels = 0
        while types.is_wrapped(unwrapped_dst_type):
            unwrapped_dst_type = unwrapped_dst_type.over
            dst_type_wrap_levels += 1

        # Convert the value to a boolean type if the target type is boolean
        bool_type = self.module.instance_type("bool")
        if dst_type == bool_type:

            # Once the source type already is a boolean just unwrap it and set it as converted value
            if unwrapped_src_type == bool_type:
                dst_value = src_value
                while dst_value.type != bool_type:
                    loaded = self.builder.load(dst_value.ir)
                    dst_value = Value(dst_value.type.over, loaded)
                return dst_value

            # Otherwise, convert the value to a boolean type
            else:
                if src_type_wrap_levels == 0:
                    value_addr = self.builder.alloca(unwrapped_src_type.ir)
                    self.builder.store(src_value.ir, value_addr)
                else:
                    value_addr = src_value.ir

                # Call the type's method used to convert value to boolean
                coerce_fn = unwrapped_src_type.select(module=self.module, node=node, name="__bool__",
                                                      positional=[None], named={})
                result = self.builder.call(coerce_fn.ir, [value_addr])
                dst_value = Value(bool_type, result)
                return dst_value
        else:

            # Unwrap the source value and set it as converted value
            dst_value = src_value
            while src_type_wrap_levels > dst_type_wrap_levels:
                loaded = self.builder.load(dst_value.ir)
                dst_value = Value(dst_value.type.over, loaded)
                src_type_wrap_levels -= 1

            numeric_types = types.INTEGERS | types.FLOATS

            # Once unwrapped source's type already is the target type just return the converted value
            if unwrapped_src_type == unwrapped_dst_type:
                return dst_value

            # Cast the src value to dst type if both are numeric
            elif unwrapped_src_type in numeric_types and unwrapped_dst_type in numeric_types:

                src_num_bits = types.BASIC[unwrapped_src_type.name]["num_bits"]
                dst_num_bits = types.BASIC[unwrapped_dst_type.name]["num_bits"]

                if (unwrapped_src_type in types.SIGNED_INTEGERS or unwrapped_src_type in types.UNSIGNED_INTEGERS) and \
                   unwrapped_dst_type in types.UNSIGNED_INTEGERS:
                    # Zero-extend the source value to fit the target type's number of bits
                    if dst_num_bits > src_num_bits:
                        coerce_fn = self.builder.zext
                    else:
                        coerce_fn = self.builder.trunc
                    result = coerce_fn(dst_value.ir, unwrapped_dst_type.ir)
                elif (unwrapped_src_type in types.SIGNED_INTEGERS or unwrapped_src_type in types.UNSIGNED_INTEGERS) and \
                     unwrapped_dst_type in types.SIGNED_INTEGERS:
                    # Zero-extend the source value to fit the target type's number of bits
                    if dst_num_bits > src_num_bits:
                        coerce_fn = self.builder.sext
                    else:
                        coerce_fn = self.builder.trunc
                    result = coerce_fn(dst_value.ir, unwrapped_dst_type.ir)
                elif unwrapped_src_type in types.FLOATS and unwrapped_dst_type in types.FLOATS:
                    # Zero-extend the source value to fit the target type's number of bits
                    if dst_num_bits > src_num_bits:
                        coerce_fn = self.builder.fpext
                    else:
                        coerce_fn = self.builder.fptrunc
                    result = coerce_fn(dst_value.ir, unwrapped_dst_type.ir)
                elif unwrapped_src_type in types.UNSIGNED_INTEGERS and unwrapped_dst_type in types.FLOATS:
                    result = self.builder.uitofp(dst_value.ir, unwrapped_dst_type.ir)
                elif unwrapped_src_type in types.SIGNED_INTEGERS and unwrapped_dst_type in types.FLOATS:
                    result = self.builder.sitofp(dst_value.ir, unwrapped_dst_type.ir)
                elif unwrapped_src_type in types.FLOATS and unwrapped_dst_type in types.UNSIGNED_INTEGERS:
                    result = self.builder.fptoui(dst_value.ir, unwrapped_dst_type.ir)
                elif unwrapped_src_type in types.FLOATS and unwrapped_dst_type in types.SIGNED_INTEGERS:
                    result = self.builder.fptosi(dst_value.ir, unwrapped_dst_type.ir)

                dst_value = Value(dst_type, result)
                return dst_value

            # If target type is a trait then convert the source value to it
            elif isinstance(unwrapped_dst_type, types.Trait) and \
                    types.is_compatible(unwrapped_src_type, unwrapped_dst_type):
                return self.cast_to_trait(dst_value, dst_type)

            # If target type is variadic arguments then just return the converted value
            elif isinstance(dst_type, types.VariadicArgs):
                return dst_value

            # If target type is a collection then convert the source value to it
            elif hasattr(unwrapped_dst_type, "elements"):
                msg = (node.pos, "mismatch types ('{right_type}' vs '{left_type}')"
                       .format(right_type=unwrapped_dst_type.name, left_type=unwrapped_src_type.name))
                hints = ["Use 'as' keyword to convert values.",
                         "Create a magic method to convert implicitly the values."]
                raise util.Error([msg], hints=hints)

            assert False, "No coerce for {src_type} -> {dst_type}".format(src_type=src_value.type, dst_type=dst_type)

    def allocate_trait_wrap(self, value_type, trait_type):
        trait_type = types.unwrap(trait_type)

        # Allocate memory to the virtual methods
        virtual_methods_type = trait_type.ir.elements[0].pointee
        virtual_methods_addr = self.builder.alloca(virtual_methods_type)

        # Allocate memory to the trait which will wrap the object and the virtual methods
        trait_wrap_addr = self.builder.alloca(trait_type.ir)

        # Traverse all trait methods to add the equivalent value's type methods to its virtual methods
        for name, trait_methods in trait_type.methods.items():
            trait_fn = trait_methods[0]

            # Get the value type's cast method with same name than current trait method to store as trait's method.
            # Example:
            #   int.__str__   ----> trait.__str__
            #   int.__bool__  ----> trait.__bool__
            # This way, for instance, when the trait's `__bool__` method is called, actually int's `__bool__` is
            # called
            if name in types.unwrap(value_type).methods:
                value_methods = types.unwrap(value_type).methods[name]
                value_fn = value_methods[0]
            else:
                msg = (trait_fn.pos,
                       "no method named '{method_name}' defined in '{trait_type}' was found in '{value_type}'"
                       .format(method_name=name, trait_type=trait_type.name, value_type=value_type.name))
                hints = ["Check whether there is a typo in the name.",
                         "Have you forgotten to define it?"]
                raise util.Error([msg], hints=hints)

            # Replace the first argument (`self`) type to a bytes pointer; this is necessary because `self`
            # can receive values of different types, so it's better receive just the address of
            # the value (bytes pointer)
            args_types = list(trait_fn.type.over["args"])
            args_types[0] = self.module.instance_type("&byte")

            ret_type = trait_fn.type.over["ret"]

            # Create a copy of the current trait method's type
            trait_fn_type = copy.copy(trait_fn.type)
            trait_fn_type.over = {"ret": ret_type, "args": args_types}

            # Store the value type's cast method into the virtual address (at index `idx`); but first cast it
            # to trait's method type (defined earlier)
            value_fn = self.builder.bitcast(value_fn.ir, trait_fn_type.ir)
            fn_addr = self.builder.gep(virtual_methods_addr, [i32(0), i32(trait_fn.idx)])
            self.builder.store(value_fn, fn_addr)

        # Store the virtual methods' addresses into the trait wrap address (at index 0)
        self.builder.store(virtual_methods_addr, self.builder.gep(trait_wrap_addr, [i32(0), i32(0)]))

        return trait_wrap_addr

    def cast_to_trait(self, value, trait_type):

        # If source value is not a pointer just create one to wrap source value with it
        if not types.is_wrapped(value.type):
            value_addr = self.builder.alloca(value.type.ir)
            self.builder.store(value.ir, value_addr)
            value = Value(types.Wrapper(value.type), value_addr)

        trait_wrap_addr = self.allocate_trait_wrap(value.type, trait_type)

        # Store the value into the trait wrap address (at index 1) reserved for hold the object of the trait; but first
        # cast the value to a bytes pointer
        value_as_bytes = self.builder.bitcast(value.ir, self.module.instance_type("&byte").ir)
        obj_addr = self.builder.gep(trait_wrap_addr, [i32(0), i32(1)])
        self.builder.store(value_as_bytes, obj_addr)

        return Value(trait_type, trait_wrap_addr)

    def check_copy_instead_move(self, src, node):

        # Objects like list's elements cannot be moved but only copied. Thus, we first check which type of
        # operation must be performed, and copy the object if necessary
        if hasattr(node, "check_copy") and node.check_copy:
            typ = types.unwrap(src.type)
            if "__copy__" in typ.methods:
                copy_fn = typ.select(module=self.module, node=node, name="__copy__", positional=[None], named={})
                src.ir = self.builder.call(copy_fn.ir, [src.ir])
            elif types.is_heap_owner(src.type):
                msg = (node.pos, "value cannot be moved here but only copied or referenced")
                hints = ["If you don't intend copy it, consider reference the value using '&' operator. "
                         "Otherwise, implement a magic method '__copy__' in '{type}'.".format(type=typ.name)]
                raise util.Error([msg], hints=hints)

        return src

    # Node visitation methods

    def visit_function(self, node):

        def allocate_args():
            """
            Hold the values of the arguments in the function's scope
            """
            if node.name != "main" and len(node.args) > 0:
                for node_arg in node.args:
                    for fn_arg in fn.args:
                        if fn_arg.name == node_arg.name:
                            arg_addr = self.builder.alloca(node_arg.type.ir)
                            self.objects[node_arg.get_name()] = Value(types.Wrapper(node_arg.type), arg_addr)
                            self.builder.store(fn_arg, arg_addr)

        self.fn = node
        if types.is_concrete(self.fn):
            fn = node.ir
            fn.attributes.add("uwtable")
            if node.is_inline:
                fn.attributes.add("alwaysinline")

            # Get special function arguments
            self.iteration_started = None
            self.next_block = None
            for arg in fn.args:
                if self.fn.has_context and arg.name == "self":
                    self_type = self.fn.args[0].type
                    self.iteration_started = ast.Attribute(None,
                                                           ast.Symbol(None, "self", internal_name="self", typ=self_type),
                                                           "$iteration_started")
                    self.next_block = ast.Attribute(None,
                                                    ast.Symbol(None, "self", internal_name="self", typ=self_type),
                                                    "$next_block")

            # Initialize scope for hold objects of the function
            self.objects = util.ScopesDict(self.objects)

            # Create all the LLVM blocks to be referenced in remain code of the function
            if self.fn.has_context:
                prologue_block = fn.append_basic_block(name="prologue")
                first_iteration_block = fn.append_basic_block(name="first_iteration")
                jump_into_next_block = fn.append_basic_block(name="indirect_branchs")
            else:
                prologue_block = None
            entry_block = fn.append_basic_block(name="entry")
            for block in sorted(node.flow.blocks, key=lambda blk: blk.id):
                if block.id > 0:
                    block.ir = fn.append_basic_block(name=block.annotation)

            # Create the prologue block if there is a generator for the function
            if self.fn.has_context:
                self.builder = ir.IRBuilder(prologue_block)
                allocate_args()

                # Load the iteration status from generator
                iteration_started_addr = self.get_attribute_addr(self.iteration_started)
                iteration_started = self.builder.load(iteration_started_addr.ir)

                # Load the current block from generator
                next_block_addr = self.get_attribute_addr(self.next_block)

                # Generate the IR object for checking the iteration status and which block it should jump into,
                # depending on its value.
                # In the first iteration, the status is 0 (not started) because no yield was used yet. Thus, the
                # execution jumps into the entry block.
                is_block_null = self.builder.icmp_signed("==", iteration_started, i1(0), name="is_block_null")
                self.builder.cbranch(is_block_null, first_iteration_block, jump_into_next_block)

                self.builder = ir.IRBuilder(first_iteration_block)

                # Save iteration status to generator as 1 (started)
                self.builder.store(i1(1), iteration_started_addr.ir)

                # Store the address of the block which the loop will jump to it once it finishes the iteration; in this
                # block the condition will be checked to see whether a new iteration will be done or whether the
                # loop is over
                next_block_address = ir.BlockAddress(fn, entry_block)
                self.builder.store(next_block_address, next_block_addr.ir)

                self.builder.branch(jump_into_next_block)

                self.builder = ir.IRBuilder(jump_into_next_block)

                # Load again the current block from generator
                next_block_address = self.builder.load(next_block_addr.ir)

                # The ‘indirectbr’ instruction implements an indirect branch to a label within the current function,
                # whose block address is specified by `next_block`.
                # The rest of the arguments indicate the full set of possible destinations that the address may
                # point to.
                # Blocks are allowed to occur multiple times in the destination list, though this isn’t particularly
                # useful.
                indirectbr = self.builder.branch_indirect(next_block_address)
                indirectbr.add_destination(entry_block)
                for target_block in node.flow.yields.values():
                    indirectbr.add_destination(target_block.ir)

            self.builder = ir.IRBuilder(entry_block)
            if not self.fn.has_context:
                allocate_args()

            # TODO: Implement sys.argv with this:
            if node.get_name() == "main" and len(node.args) > 0:

                # Get 'argc' and 'argv' arguments
                argc, argv = None, None
                for arg in fn.args:
                    if arg.name == "argc":
                        argc = arg
                    elif arg.name == "argv":
                        argv = arg

                # Hold the variable `args` in the function's scope; for this process argc and argv arguments
                # through `__args__` function
                typ = types.Wrapper(self.module.instance_type("list<str>"))
                args_addr = self.builder.alloca(typ.ir)
                get_args_fn = self.module.symbols["__args__"].ir
                ret = self.builder.call(get_args_fn, [argc, argv])
                self.builder.store(ret, args_addr)
                self.objects["args$0"] = Value(types.Wrapper(typ), args_addr)

            # Visit the function blocks to generate the IR
            for block in sorted(node.flow.blocks, key=lambda blk: blk.id):
                self.visit(block)

            # Return to the outer scope
            self.objects = self.objects.parent

    def visit_beginscope(self, node):
        pass

    def visit_endscope(self, node):
        pass

    def visit_block(self, node):

        # Create an IR builder for this block
        # This builder will be passed to all functions that process the nodes of this block
        if node.id > 0:
            block = node.ir
            self.builder = ir.IRBuilder(block)

        # Generate IR objects for each step of this block
        for step in sorted(node.steps, key=lambda stp: stp.id):
            self.visit(step)

    # Basic types

    def visit_noneval(self, node):

        # Create an instance of None value
        none = node.type.ir(None)

        return Value(node.type, none)

    def visit_bool(self, node):
        return Value(node.type, i1(1) if node.literal else i1(0))

    def visit_int(self, node):
        return Value(node.type, node.type.ir(node.literal))

    def visit_float(self, node):
        return Value(node.type, node.type.ir(node.literal))

    def visit_byte(self, node):
        return Value(node.type, node.type.ir(node.literal))

    # Structures

    def visit_array(self, node):
        array_type = types.unwrap(node.type)

        # Note:
        # A `array` object have three attributes:
        #   `data`: the pointer to a contiguous block of memory which store the list's items
        #   `len`: the number of items
        # So it must be allocated the `list` object as well as these two attributes

        len_type = array_type.attributes["len"]["type"]
        data_type = array_type.attributes["data"]["type"]

        # Check if the array's data must be allocated on heap or stack memory
        # In other words, whether its content should or not be freed after call, different memory allocations
        # should be used for each case
        if types.is_heap_owner(node.type):

            # Allocate "heap" memory to the list
            array_addr = self.heap_alloc(array_type.ir, 1)

        else:

            # Allocate "stack" memory to the list
            array_addr = self.builder.alloca(array_type.ir)

        # Visit the num_elements expression to generate their IR objects
        num_elements = self.visit(node.num_elements)
        num_elements = self.coerce(num_elements, self.module.instance_type("int"), node.num_elements)

        # Allocate space in "heap" memory to store the array's items
        data_addr = self.heap_alloc(data_type.over.ir, num_elements)

        # Call the '__init__' function of the array
        init_fn = array_type.select(module=self.module, node=node, name="__init__",
                                    positional=[None, len_type, data_type], named={})
        self.builder.call(init_fn.ir, [array_addr, num_elements.ir, data_addr])

        return Value(node.type, array_addr)

    def visit_string(self, node):
        str_type = types.unwrap(node.type)

        # Replace escape characters to literal characters
        literal = node.literal

        # Note:
        # A `str` object have one single attribute:
        #   `array`: the array of bytes containing the string
        # So it must be allocated the `str` object as well as this attribute

        length = len(literal)
        array_type = types.unwrap(str_type.attributes["arr"]["type"])
        len_type = array_type.attributes["len"]["type"]
        data_type = array_type.attributes["data"]["type"]
        data_type_as_bytearray = ir.ArrayType(data_type.over.ir, length)

        # Create a constant to represent the literal string; the data type must be always an array of
        # integers where each array's element represents a single character code
        data_initializer = ir.Constant(data_type_as_bytearray, bytearray(literal.encode("utf8")))

        # Check if the string's data must be allocated on heap or stack memory
        # In other words, whether its content should or not be freed after call, different memory allocations
        # should be used for each case
        if types.is_heap_owner(node.type):

            # Allocate "heap" memory to the string
            str_addr = self.heap_alloc(str_type.ir, 1)

            # Allocate "heap" memory to the string's array
            array_addr = self.heap_alloc(array_type.ir, 1)

        else:

            # Allocate "stack" memory to the string
            str_addr = self.builder.alloca(str_type.ir)

            # Allocate "stack" memory to the string's array
            array_addr = self.builder.alloca(array_type.ir)

        # Allocate space in "heap" memory to store the string's bytes
        data_addr = self.heap_alloc(data_type.over.ir, length)

        # Convert `data` pointer to `data_type_as_bytearray` pointer type to store the literal string
        data_as_bytearray = self.builder.bitcast(data_addr, data_type_as_bytearray.as_pointer())

        # Store the literal string into `data` attribute
        self.builder.store(data_initializer, data_as_bytearray)

        # Call the '__init__' function of the string
        init_fn = array_type.select(module=self.module, node=node, name="__init__",
                                    positional=[None, len_type, data_type], named={})
        self.builder.call(init_fn.ir, [array_addr, integer(length), data_addr])

        # Call the '__init__' function of the array
        init_fn = str_type.select(module=self.module, node=node, name="__init__", positional=[None, array_type],
                                  named={})
        self.builder.call(init_fn.ir, [str_addr, array_addr])

        return Value(node.type, str_addr)

    def visit_tuple(self, node):
        tuple_type = types.unwrap(node.type)

        if types.is_heap_owner(node.type):

            # Allocate "heap" memory to the tuple
            tuple_addr = self.heap_alloc(tuple_type.ir, 1)

        else:

            # Allocate "stack" memory to the tuple
            tuple_addr = self.builder.alloca(tuple_type.ir)

        # Store the length of list into address of `len` attribute
        len_idx = tuple_type.attributes["len"]["idx"]
        len_addr = self.builder.gep(tuple_addr, [i32(0), i32(len_idx)])
        self.builder.store(integer(len(node.elements)), len_addr)

        # Traverse all elements from tuple's node
        # We start from second element because the first one is the `len` attribute
        for i, element in enumerate(node.elements):

            # Get the memory address of the element
            element_idx = tuple_type.attributes["element_" + str(i)]["idx"]
            dst_addr = self.builder.gep(tuple_addr, [i32(0), i32(element_idx)])

            # Visit the element to get its IR object
            # Convert the value to tuple's type if necessary
            # Integer and floats even being compatible still need be casted from each one to another one
            src = self.visit(element)
            src = self.coerce(src, element.type, element)
            src = self.check_copy_instead_move(src, element)

            # Store the IR node into address of the element
            self.builder.store(src.ir, dst_addr)

        return Value(node.type, tuple_addr)

    def visit_list(self, node):
        list_type = types.unwrap(node.type)

        # Note:
        # A `list` object have three attributes:
        #   `data`: the pointer to a contiguous block of memory which store the list's items
        #   `len`: the number of items
        #   `allocated`: the memory size allocated for the items
        # So it must be allocated the `list` object as well as these two attributes

        length = len(node.elements)
        array_type = types.unwrap(list_type.attributes["arr"]["type"])
        len_type = list_type.attributes["len"]["type"]
        data_type = array_type.attributes["data"]["type"]

        # Check if the list's data must be allocated on heap or stack memory
        # In other words, whether its content should or not be freed after call, different memory allocations
        # should be used for each case
        if types.is_heap_owner(node.type):

            # Allocate "heap" memory to the list
            list_addr = self.heap_alloc(list_type.ir, 1)

            # Allocate "heap" memory to the list's array
            array_addr = self.heap_alloc(array_type.ir, 1)

        else:

            # Allocate "stack" memory to the list
            list_addr = self.builder.alloca(list_type.ir)

            # Allocate "stack" memory to the list's array
            array_addr = self.builder.alloca(array_type.ir)

        # Allocate space in "heap" memory to store the list's items
        data_addr = self.heap_alloc(data_type.over.ir, length)

        # Call the '__init__' function of the list
        init_fn = array_type.select(module=self.module, node=node, name="__init__",
                                    positional=[None, len_type, data_type], named={})
        self.builder.call(init_fn.ir, [array_addr, integer(length), data_addr])

        # Call the '__init__' function of the array
        init_fn = list_type.select(module=self.module, node=node, name="__init__", positional=[None, array_type],
                                   named={})
        self.builder.call(init_fn.ir, [list_addr, array_addr])

        # Once the list's items could not be literal, each item must be initialized in an individual way
        for i, element in enumerate(node.elements):

            # Visit the element to get its IR object
            # Convert the value to list's type if necessary
            # Integer and floats even being compatible still need be casted from each one to another one
            src = self.visit(element)
            src = self.coerce(src, array_type.elements[0], element)
            src = self.check_copy_instead_move(src, element)

            # Get the memory address of the element
            dst_addr = self.builder.gep(data_addr, [i32(i)])

            # Store the IR node into address of the element
            self.builder.store(src.ir, dst_addr)

        return Value(node.type, list_addr)

    def visit_dict(self, node):
        dict_type = types.unwrap(node.type)

        # Note:
        # A `dict` object have two attributes:
        #   `buckets`: the list of buckets which store the dictionary's items
        #   `len`: the number of items
        # So it must be allocated the `dict` object as well as these two attributes

        # Check if the dict must be allocated on heap or stack memory
        # In other words, whether its content should or not be freed after call, different memory allocations
        # should be used for each case
        if types.is_heap_owner(node.type):

            # Allocate "heap" memory to the dict
            dict_addr = self.heap_alloc(dict_type.ir, 1)

        else:

            # Allocate "stack" memory to the dict
            dict_addr = self.builder.alloca(dict_type.ir)

        # Call the '__init__' function of the set
        init_fn = dict_type.select(module=self.module, node=node, name="__init__", positional=[None], named={})
        self.builder.call(init_fn.ir, [dict_addr])

        # Every item must be added in an individual way using the proper '__setitem__' call
        key_type, value_type = dict_type.elements
        set_item_fn = dict_type.select(module=self.module, node=node, name="__setitem__",
                                       positional=[None, key_type, value_type], named={})
        for element_key, element_value in node.elements.items():

            # Visit the key to get its IR object
            # Convert the value to list's type if necessary
            # Integer and floats even being compatible still need be casted from each one to another one
            key = self.visit(element_key)
            key = self.coerce(key, key_type, element_key)

            # Visit the value to get its IR object
            # Convert the value to list's type if necessary
            # Integer and floats even being compatible still need be casted from each one to another one
            value = self.visit(element_value)
            value = self.coerce(value, value_type, element_value)
            value = self.check_copy_instead_move(value, element_value)

            # Call the type's method used to add value in the set
            self.builder.call(set_item_fn.ir, [dict_addr, key.ir, value.ir])

        return Value(node.type, dict_addr)

    def visit_set(self, node):
        set_type = types.unwrap(node.type)

        # Note:
        # A `set` object have two attributes:
        #   `buckets`: the list of buckets which store the set's items
        #   `len`: the number of items
        # So it must be allocated the `set` object as well as these two attributes

        # Check if the set must be allocated on heap or stack memory
        # In other words, whether its content should or not be freed after call, different memory allocations
        # should be used for each case
        if types.is_heap_owner(node.type):

            # Allocate "heap" memory to the set
            set_addr = self.heap_alloc(set_type.ir, 1)

        else:

            # Allocate "stack" memory to the set
            set_addr = self.builder.alloca(set_type.ir)

        # Call the '__init__' function of the set
        init_fn = set_type.select(module=self.module, node=node, name="__init__", positional=[None], named={})
        self.builder.call(init_fn.ir, [set_addr])

        # Every item must be added in an individual way using the proper 'add' call
        element_type = set_type.elements[0]
        add_fn = set_type.select(module=self.module, node=node, name="add", positional=[None, element_type], named={})
        for element in node.elements:

            # Visit the element to get its IR object
            # Convert the value to set's type if necessary
            # Integer and floats even being compatible still need be casted from each one to another one
            value = self.visit(element)
            value = self.coerce(value, element_type, element)
            value = self.check_copy_instead_move(value, element)

            # Call the type's method used to add value in the set
            self.builder.call(add_fn.ir, [set_addr, value.ir])

        return Value(node.type, set_addr)

    def get_attribute_addr(self, node):
        #TODO: Should we check here if object is Null and then thrown NullPointerException?

        # Visit the object (ie an instance of class) to get its IR object
        obj = self.visit(node.obj)

        # Get the type of the object expression
        obj_type = types.unwrap(obj.type)

        # Get the memory address of the attribute based on its index in the object's class
        attribute = obj_type.attributes[node.attribute]
        attribute_addr = self.builder.gep(obj.ir, [i32(0), i32(attribute["idx"])])

        return Value(types.Wrapper(attribute["type"]), attribute_addr)

    def visit_attribute(self, node):

        # Visit the attribute of an object (a class instance) to get its IR object
        attribute_addr = self.get_attribute_addr(node)
        attribute = self.builder.load(attribute_addr.ir)
        attribute_type = attribute_addr.type.over

        return Value(attribute_type, attribute)

    def visit_setattribute(self, node):
        return self.get_attribute_addr(node)

    def visit_element(self, node):
        # TODO: Should we check here if object is Null and then thrown NullPointerException?

        # Visit the list to get its IR object
        obj = self.visit(node.obj)

        # Get the type of the object expression
        obj_type = types.unwrap(obj.type)

        # Visit the key (ie the list's index to extract the element) to get its IR object
        key = self.visit(node.key)

        if obj_type.name.startswith("data<"):

            # Get value at given offset
            offset_addr = self.builder.gep(obj.ir, [key.ir])
            if not types.is_wrapped(node.type):
                element = self.builder.load(offset_addr)
            else:
                element = offset_addr

        else:

            if types.unwrap(obj.type).name.startswith("tuple<"):

                # Get value at given index
                element_idx = obj_type.attributes["element_" + str(node.key.literal)]["idx"]
                element_addr = self.builder.gep(obj.ir, [i32(0), i32(element_idx)])
                element = self.builder.load(element_addr)

            else:

                # Call the type's method used to get value of the list's element
                get_item_fn = obj_type.select(module=self.module, node=node.key, name="__getitem__",
                                              positional=[None, key.type], named={})
                key = self.coerce(key, get_item_fn.type.over["args"][1], node.key)
                element = self.builder.call(get_item_fn.ir, [obj.ir, key.ir])

        return Value(node.type, element)

    def visit_setelement(self, node):
        return self.visit_element(node)

    # Boolean operators

    def visit_not(self, node):

        # Visit the expression to get its IR object
        # If expression result is not boolean then convert it
        expression = self.visit(node.value)
        if types.unwrap(expression.type) != self.module.instance_type("bool"):
            expression = self.coerce(expression, self.module.instance_type("bool"), node.value)

        # Summarize the boolean expression result to a simple integer of 0 or 1 values
        result = self.builder.select(expression.ir, i1(0), i1(1))

        return Value(self.module.instance_type("bool"), result)

    def boolean(self, node):

        # Visit the left and right expressions to generate their IR objects
        left = self.visit(node.left)
        right = self.visit(node.right)

        # Get the type of the left expression
        left_type = types.unwrap(left.type)

        # If left expression type is not a boolean then call its internal method (`__bool__`) to convert it to boolean
        if left_type == self.module.instance_type("bool"):
            expression = left.ir
        else:
            fn = left_type.select(module=self.module, node=node.left, name="__bool__", positional=[None], named={})
            arg = self.coerce(left, fn.type.over["args"][0], node.left)
            expression = self.builder.call(fn.ir, [arg.ir])

        # Generate the IR object for perform the boolean expression
        if node.op == "and":
            result = self.builder.select(expression, right.ir, left.ir)
        elif node.op == "or":
            result = self.builder.select(expression, left.ir, right.ir)

        return Value(left.type, result)

    def visit_and(self, node):
        return self.boolean(node)

    def visit_or(self, node):
        return self.boolean(node)

    # Comparison operators

    def visit_is(self, node):

        # Visit the left expression to get its IR object
        left = self.visit(node.left)

        # Generate the IR object for checking of the type
        result = self.builder.icmp_signed("==", left.ir, left.ir.type(None))

        return Value(self.module.instance_type("bool"), result)

    def compare(self, node):

        # Visit the left and right expressions to generate their IR objects
        left = self.visit(node.left)
        right = self.visit(node.right)

        # Prepare a dictionary for symbol and its 'magic' function
        ops = {"==": "eq",
               "!=": "ne",
               "<": "lt",
               "<=": "le",
               ">": "gt",
               ">=": "ge"}

        # If both left and right expression are numeric values generate IR objects for general comparison
        numeric_types = {self.module.instance_type("bool")} | types.INTEGERS | types.FLOATS
        if types.unwrap(left.type) in numeric_types:

            # Unwrap the types of the left and right expressions
            if types.is_wrapped(left.type):
                loaded = self.builder.load(left.ir)
                left = Value(left.type.over, loaded)
            if types.is_wrapped(right.type):
                loaded = self.builder.load(right.ir)
                right = Value(right.type.over, loaded)

            # Convert the other number of smaller type to bigger type if necessary
            bigger_type = types.choose_bigger_type(left.type, right.type)
            if left.type != bigger_type:
                left = self.coerce(left, bigger_type, node.left)
            elif right.type != bigger_type:
                right = self.coerce(right, bigger_type, node.right)

            # If any one of the numbers is float, then use a LLVM function for floating numbers
            if bigger_type in types.FLOATS:
                compare_fn = self.builder.fcmp_ordered

            # Use a LLVM function for integer numbers
            else:

                # If any one of the integers is signed, then use a LLVM function for signed integers
                if bigger_type in types.SIGNED_INTEGERS:
                    compare_fn = self.builder.icmp_signed
                else:
                    compare_fn = self.builder.icmp_unsigned

            # Generate the IR object calling the proper function for perform the comparison expression according to
            # numeric types (bool, integer or float)
            result = compare_fn(node.op, left.ir, right.ir)

        # Otherwise use the type's method for perform the same comparison (operator overload)
        else:

            # Sometimes the type have a method `__eq__` but not a `__ne__`; if we need certain method, but it doesn't
            # exist it is just use its antagonist one that exists and then invert the final boolean expression to get
            # the same result
            inverse = False
            compare_object_id = False
            if node.op in {"==", "!="}:
                antagonist = {"==": "!=", "!=": "=="}
                op = "__{op}__".format(op=ops[node.op])
                antagonic_op = "__{op}__".format(op=ops[antagonist[node.op]])
                if op not in left.type.over.methods:
                    if antagonic_op in left.type.over.methods:
                        node.op = antagonist[node.op]
                        inverse = True
                    else:
                        compare_object_id = True

            if not compare_object_id:

                # Call the type's method used to perform the operator overloading
                left_type = types.unwrap(left.type)
                fn = left_type.select(module=self.module, node=node.left, name="__{op}__".format(op=ops[node.op]),
                                      positional=[None, right.type], named={})
                args = [arg.ir for arg in (left, right)]
                result = self.builder.call(fn.ir, args)

                # Inverse the boolean result if defined earlier
                if inverse:
                    result = self.builder.select(result, i1(0), i1(1))

            else:

                # Get the left object's ID
                left_id_idx = types.unwrap(left.type).attributes["id"]["idx"]
                left_id_addr = self.builder.gep(left.ir, [i32(0), i32(left_id_idx)])
                left_id = self.builder.load(left_id_addr)

                # Get the right object's ID
                right_id_idx = types.unwrap(right.type).attributes["id"]["idx"]
                right_id_addr = self.builder.gep(right.ir, [i32(0), i32(right_id_idx)])
                right_id = self.builder.load(right_id_addr)

                # Call the function to compare the objects' IDs
                result = self.builder.icmp_unsigned(node.op, left_id, right_id)

        return Value(self.module.instance_type("bool"), result)

    def visit_equal(self, node):
        return self.compare(node)

    def visit_notequal(self, node):
        return self.compare(node)

    def visit_lowerthan(self, node):
        return self.compare(node)

    def visit_lowerequal(self, node):
        return self.compare(node)

    def visit_greaterthan(self, node):
        return self.compare(node)

    def visit_greaterequal(self, node):
        return self.compare(node)

    # Arithmetic operators

    def unary_arith(self, node):

        # Visit the expression to get its IR object
        # If expression result is not boolean then convert it
        expression = self.visit(node.value)

        # Prepare a dictionary for symbol and its 'magic' function
        ops = {"-": "neg",
               "not": "not"}

        # If both left and right expression are numeric values generate IR objects for general mathematical operation
        numeric_types = types.INTEGERS | types.FLOATS
        if types.unwrap(expression.type) in numeric_types:

            # Unwrap the types of the left and right expressions
            if types.is_wrapped(expression.type):
                loaded = self.builder.load(expression.ir)
                expression = Value(expression.type.over, loaded)

            typ = expression.type

            # If any one of the numbers is float, then use a LLVM function for floating numbers
            arith_fn = None
            if typ in types.FLOATS:

                # Get the proper llvm function to perform the operation
                if node.op == "-":
                    arith_fn = self.builder.fneg

            # Use a LLVM function for integer numbers
            else:

                # Get the proper llvm function to perform the operation
                if node.op == "-":
                    arith_fn = self.builder.neg
                elif node.op == "~":
                    arith_fn = self.builder.not_

            # Generate the IR object calling the proper function for perform the mathematical operation according to
            # operator
            result = arith_fn(expression.ir)

            return Value(expression.type, result)

        # Otherwise use the type's method for perform the same mathematical operation (operator overload)
        else:

            # Call the type's method used to perform the operator overloading
            expression_type = types.unwrap(expression.type)
            fn = expression_type.select(self.module, expression, "__{op}__".format(op=ops[node.op]),
                                        (expression.type,), {})
            result = self.builder.call(fn.ir, [expression.ir])

            return Value(fn.type.over["ret"], result)

    def binary_arith(self, node):

        # Visit the left and right expressions to generate their IR objects
        left = self.visit(node.left)
        right = self.visit(node.right)

        # Prepare a dictionary for symbol and its 'magic' function
        ops = {"+": "add",
               "-": "sub",
               "*": "mul",
               "/": "truediv",
               "//": "floordiv",
               "%": "mod",
               "**": "pow",
               ">>": "rshift",
               "<<": "lshift",
               "&": "and",
               "|": "or",
               "^": "xor"}

        # If both left and right expression are numeric values generate IR objects for general mathematical operation
        numeric_types = types.INTEGERS | types.FLOATS
        if types.unwrap(left.type) in numeric_types:

            # Unwrap the types of the left and right expressions
            if types.is_wrapped(left.type):
                loaded = self.builder.load(left.ir)
                left = Value(left.type.over, loaded)
            if types.is_wrapped(right.type):
                loaded = self.builder.load(right.ir)
                right = Value(right.type.over, loaded)

            arith_fn = None

            if node.op == "**":

                def convert_to_llvm(typ):
                    if typ in types.INTEGERS:
                        preffix = "i"
                    elif typ in types.FLOATS:
                        preffix = "f"
                    else:
                        assert False, "Type not allowed for this operation"
                    return "{preffix}{bits}".format(preffix=preffix, bits=types.BASIC[typ.name]["num_bits"])

                # llvm.powi.* only accepts at moment:
                #   numbers: f32, f64
                #   exponents: i32
                if left.type not in types.FLOATS:
                    left = self.coerce(left, self.module.instance_type("f64"), node.left)
                right = self.coerce(right, self.module.instance_type("i32"), node.right)

                # Use the LLVM function for exponentiation
                number = convert_to_llvm(left.type)
                exponent = convert_to_llvm(right.type)
                arith_fn = self.module.symbols["llvm.powi.{number}.{exponent}".format(number=number,
                                                                                      exponent=exponent)].ir
                result = self.builder.call(arith_fn, [left.ir, right.ir])

                return Value(left.type, result)

            else:

                # Convert the other number of smaller type to bigger type if necessary
                bigger_type = types.choose_bigger_type(left.type, right.type)
                if left.type != bigger_type:
                    left = self.coerce(left, bigger_type, node.left)
                elif right.type != bigger_type:
                    right = self.coerce(right, bigger_type, node.right)

                # If any one of the numbers is float, then use a LLVM function for floating numbers
                result_is_signed = None
                if bigger_type in types.FLOATS:

                    # Get the proper llvm function to perform the operation
                    if node.op == "+":
                        arith_fn = self.builder.fadd
                    elif node.op == "-":
                        arith_fn = self.builder.fsub
                    elif node.op == "*":
                        arith_fn = self.builder.fmul
                    elif node.op == "/" or node.op == "//":
                        arith_fn = self.builder.fdiv
                    elif node.op == "%":
                        arith_fn = self.builder.frem

                # Use a LLVM function for integer numbers
                else:

                    # If any one of the integers is signed, then use a LLVM function for signed integers
                    if bigger_type in types.SIGNED_INTEGERS:
                        result_is_signed = True
                    else:
                        result_is_signed = True

                    # Get the proper llvm function to perform the operation
                    if node.op == "+":
                        arith_fn = self.builder.add
                    elif node.op == "-":
                        arith_fn = self.builder.sub
                    elif node.op == "*":
                        arith_fn = self.builder.mul
                    elif node.op == "/" or node.op == "//":
                        if result_is_signed:
                            arith_fn = self.builder.sdiv
                        else:
                            arith_fn = self.builder.udiv
                    elif node.op == "%":
                        if result_is_signed:
                            arith_fn = self.builder.srem
                        else:
                            arith_fn = self.builder.urem
                    elif node.op == "&":
                        arith_fn = self.builder.and_
                    elif node.op == "|":
                        arith_fn = self.builder.or_
                    elif node.op == "^":
                        arith_fn = self.builder.xor
                    elif node.op == "<<":
                        arith_fn = self.builder.shl
                    elif node.op == ">>":
                        arith_fn = self.builder.ashr

                # Generate the IR object calling the proper function for perform the mathematical operation according to
                # operator
                result = arith_fn(left.ir, right.ir)

                # In case of floor division truncate the result to integer to round it
                if node.op == "//":
                    if bigger_type in types.INTEGERS:
                        if result_is_signed:
                            result = self.builder.fptosi(result, bigger_type.ir)
                        else:
                            result = self.builder.fptoui(result, bigger_type.ir)
                    elif bigger_type in types.FLOATS:
                        rounded = self.builder.fptosi(result, i32)
                        result = self.builder.sitofp(rounded, bigger_type.ir)

                return Value(bigger_type, result)

        # Otherwise use the type's method for perform the same mathematical operation (operator overload)
        else:

            # Call the type's method used to perform the operator overloading
            left_type = types.unwrap(left.type)
            fn = left_type.select(self.module, left, "__{op}__".format(op=ops[node.op]), (left.type, right.type), {})
            args = [arg.ir for arg in (left, right)]
            ret_type = fn.type.over["ret"]
            result = self.builder.call(fn.ir, args)

            return Value(ret_type, result)

    def visit_neg(self, node):
        return self.unary_arith(node)

    def visit_add(self, node):
        return self.binary_arith(node)

    def visit_sub(self, node):
        return self.binary_arith(node)

    def visit_mul(self, node):
        return self.binary_arith(node)

    def visit_div(self, node):
        return self.binary_arith(node)

    def visit_mod(self, node):
        return self.binary_arith(node)

    def visit_floordiv(self, node):
        return self.binary_arith(node)

    def visit_pow(self, node):
        return self.binary_arith(node)

    # Bitwise operators

    def visit_bwnot(self, node):
        return self.unary_arith(node)

    def visit_bwand(self, node):
        return self.binary_arith(node)

    def visit_bwor(self, node):
        return self.binary_arith(node)

    def visit_bwxor(self, node):
        return self.binary_arith(node)

    def visit_bwshiftleft(self, node):
        return self.binary_arith(node)

    def visit_bwshiftright(self, node):
        return self.binary_arith(node)

    # Control flow

    def visit_pass(self, node):
        pass

    def visit_branch(self, node):
        # Generate the IR object that makes execution unconditionally jump to a given block
        self.builder.branch(node.target_block.ir)

    def visit_condbranch(self, node):

        # Visit the condition to get its IR object
        # If condition type is not boolean then convert it
        cond = self.visit(node.cond)
        if cond.type != self.module.instance_type("bool"):
            cond = self.coerce(cond, self.module.instance_type("bool"), node.cond)

        # Generate the IR object for checking the condition and which block it should jump into, depending on its value
        self.builder.cbranch(cond.ir, node.is_true_block.ir, node.is_false_block.ir)

    def visit_phi(self, node):

        # Visit the left and right expressions to generate their IR objects
        left = self.visit(node.left[1])
        right = self.visit(node.right[1])

        # Generate the IR object for checking the condition and which value a variable must be set, depending on it
        result = self.builder.phi(left.type.ir)
        result.add_incoming(left.ir, node.left[0].ir)
        result.add_incoming(right.ir, node.right[0].ir)

        return Value(left.type, result)

    def visit_raise(self, node):

        # Visit the exception to get its IR object
        exception = self.visit(node.value)

        # Call `__raise__` function to thrown exception; if there's a call branch, ie the call is inside a `try`
        # statement then jump to normal block if call was ok else jump to exception block to handle the error
        raise_fn = self.module.symbols["__raise__"].ir
        if node.call_branch is None:
            call_instr = self.builder.call(raise_fn, [exception.ir])
            call_instr.attributes.add("noreturn")
            self.builder.unreachable()
        else:
            normal_block = node.call_branch["normal_block"]
            exception_block = node.call_branch["exception_block"]
            call_instr = self.builder.invoke(raise_fn, [exception.ir], normal_block.ir, exception_block.ir)
            call_instr.attributes.add("noreturn")

    def visit_landingpad(self, node):

        # Once the function has landing pad, a personality function must set to it
        self.builder.function.attributes.personality = self.module.ir.get_global("__ragaz_personality")

        # Note:
        # Personality function is part of the exception handling. The gcc EH mechanism allows mixing various EH models,
        # and a personality routine is invoked to determine if an exception match, what finalization to invoke,
        # etc. This specific personality routine is for C++ exception handling

        # Generate the IR object for the landing pad; the return type (`typ`) of the landing pad is a structure
        # with 2 pointer-sized fields
        typ = ir.LiteralStructType([i8.as_pointer(), i32])
        landing_pad = self.builder.landingpad(typ)

        # Add catch clauses to the landing pad:
        #   A CatchClause specifies a typeinfo for a single exception to be caught; so exception type like OSError,
        #   OverflowError, etc. will have a distinct type_info
        for typ in node.map:
            clause = ir.CatchClause(self.module.ir.get_global(typ.name + ".size"))
            landing_pad.add_clause(clause)

        # Hold the landing pad into function's scope
        self.objects[node.var] = landing_pad

        # Extract the landing pad's return
        result = self.builder.extract_value(landing_pad, 1)

        # Note:
        # In Ragaz there's only an exception type (yet): `Exception` and thus only it will be handled in
        # the following code...

        # Convert `Exception` type to `typeid` function's argument pointer
        exception_size = self.module.ir.get_global("Exception.size")
        exception = self.builder.bitcast(exception_size, i8.as_pointer())

        # Call `typeid` function to find out the typeinfo of the `Exception` type in LLVM
        typeid_fn = self.module.ir.get_global("llvm.eh.typeid.for")
        type_info = self.builder.call(typeid_fn, [exception])
        type_info.attributes.add("nounwind")

        # Generate the IR object for checking if the landing pad's return has the same type_info as the `Exception`
        # type_info; if it's true then jump the execution into the proper block in catches map else jump into fail block
        match = self.builder.icmp_signed("==", result, type_info)
        is_true_block = list(node.map.values())[0]  # The list of mapped exceptions have only an item (yet): Exception
        is_false_block = node.fail_block
        self.builder.cbranch(match, is_true_block.ir, is_false_block.ir)

    def visit_resume(self, node):

        # Get the landing pad from function's scope
        landingpad = self.objects[node.var]

        # Generate the IR object for resume; Resume instruction is used to indicate that the landing pad did not
        # catch the exception after all, perhaps because it only performed cleanup
        self.builder.resume(landingpad)

    def visit_call(self, node):

        def process_arg(arg, formal_type):
            value = self.visit(arg)
            value = self.coerce(value, formal_type, arg)
            value = self.check_copy_instead_move(value, arg)
            value = self.check_wrap(value, formal_type, arg)
            return value

        # Set arguments and return types
        args = []
        ret_type, formal_args_types = node.fn.type.over["ret"], node.fn.type.over["args"]

        # If the called function is virtual, ie it's the method of a trait, then call the proper method which it
        # references
        if node.virtual:

            # Visit the trait (ie the first argument of the call) to get its IR object
            trait_wrap_addr = self.visit(node.args[0])

            # Get the object from the trait wrap address (at index 1) and put it as `self` argument of the function
            self_addr = self.builder.gep(trait_wrap_addr.ir, [i32(0), i32(1)])
            self_obj = Value(self.module.instance_type("&byte"), self.builder.load(self_addr))

            # Get the virtual methods' addresses from the trait wrap address (at index 0)
            virtual_methods_addr = self.builder.gep(trait_wrap_addr.ir, [i32(0), i32(0)])

            # Set the trait's method as the function to call
            virtual_methods = self.builder.load(virtual_methods_addr)
            fn_addr = self.builder.gep(virtual_methods, [i32(0), i32(node.fn.idx)])
            call_fn = self.builder.load(fn_addr)

            # Put object as `self` argument of the function
            args.append(self_obj)

        else:

            # Set the proper function to call
            # Usually this function is specified in the call itself but sometimes a variable or attribute is pointing
            # to it
            if isinstance(node.fn, ast.Function):
                call_fn = node.fn.ir
            else:
                if isinstance(node.fn, ast.Attribute):
                    fn_addr = self.visit(node.fn)
                    fn = fn_addr.ir
                else:
                    fn_addr = self.objects[node.fn.get_name()]
                    fn = self.builder.load(fn_addr.ir)
                call_fn = fn

            if len(node.args) > 0:

                # Process the first element, being it passed as 'self' or not
                value = process_arg(node.args[0], formal_args_types[0])

                args.append(value)

        # Visit each call's arguments and if necessary, convert the argument to the formal type (that type declared
        # by the function)
        for arg, formal_arg_type in zip(node.args[1:], formal_args_types[1:]):
            value = process_arg(arg, formal_arg_type)
            args.append(value)

        # Call the function; if there's a call branch, ie the call is inside a `try` statement then jump to normal block
        # # if call was ok else jump to exception block to handle the error
        if node.call_branch is None:
            result = self.builder.call(call_fn, [arg.ir for arg in args])
        else:
            normal_block = node.call_branch["normal_block"]
            exception_block = node.call_branch["exception_block"]
            result = self.builder.invoke(call_fn, [arg.ir for arg in args],
                                         normal_to=normal_block.ir,
                                         unwind_to=exception_block.ir)

        # If the call return nothing...
        if ret_type == self.module.instance_type("void"):

            # ... but the first argument is the `self` instance created the `__init__` constructor, return it
            if len(node.args) > 0 and isinstance(node.args[0], ast.Init):
                return args[0]

            # Otherwise, return nothing
            else:
                return None

        # Otherwise, return the call's result if previous conditions are false
        else:
            return Value(ret_type, result)

    def visit_yield(self, node):

        # Note:
        # The yield statement suspends function’s execution and sends a value back to the caller, but retains enough
        # state (ie in generator) to enable function to resume where it is left off. When resumed, the
        # function continues execution immediately after the last yield run (using the jump address set previously).

        # Store the address of the block which the caller will jump to it once the caller continue the execution
        next_block_addr = self.get_attribute_addr(self.next_block)
        next_block_address = ir.BlockAddress(self.fn.ir, node.target_block.ir)
        self.builder.store(next_block_address, next_block_addr.ir)

        # Visit the yield value to get its IR object
        value = self.visit(node.value)
        yield_type = self.fn.type.over["ret"]
        value = self.coerce(value, yield_type, node.value)

        # Generate the IR object that return the yield_value
        self.builder.ret(value.ir)

    def visit_return(self, node):

        # If there's a return value...
        if node.value is not None:
            value = self.visit(node.value)
            ret_type = self.fn.type.over["ret"]
            value = self.coerce(value, ret_type, node.value)

            if types.is_wrapped(value.type) and value.type.over.byval:
                loaded = self.builder.load(value.ir)
                value = Value(value.type.over, loaded)
            self.builder.ret(value.ir)

        # Otherwise. if there's no return value...
        else:

            # ...and function is `main`, then force it to return zero once it needs return a value
            if self.main is not None and self.main.type.over["ret"].ir == void:
                self.builder.ret(i32(0))

            # ...return None if it's a generator
            elif self.fn.has_context:
                ret_type = self.fn.type.over["ret"].ir
                self.builder.ret(ret_type(None))

            # ...return void if the previous conditions are false
            else:
                self.builder.ret_void()

    # Symbols

    def visit_symbol(self, node, dereference=True):

        # Get the variable from function's scope
        var = self.objects[node.get_name()]

        # If this variable is not a named variable (example $0, %3, etc.) neither its content is a function then
        # create an instance of `Value` for the variable
        if not node.is_hidden() and not isinstance(var.type, types.Function):
            value = self.builder.load(var.ir)
            var = Value(var.type.over, value)

        # Unwrap the object as it could be a reference to other object
        if dereference:
            while hasattr(var.type, "over") and types.is_wrapped(var.type.over):
                loaded = self.builder.load(var.ir)
                var = Value(var.type.over, loaded)

        return var

    def visit_variabledeclaration(self, node):

        def hold_variable(variable):
            var_addr = self.builder.alloca(variable.type.ir,
                                           name=variable.get_name())
            var = Value(types.Wrapper(variable.type), var_addr)
            self.objects[variable.get_name()] = var

        # Handle every element of the tuple
        if isinstance(node.variables, ast.Tuple):
            for i, element in enumerate(node.variables.elements):
                hold_variable(element)

        # Handle the single variable
        elif isinstance(node.variables, ast.Symbol):
            hold_variable(node.variables)

    def visit_assign(self, node):

        def set_left_value(left, right):

            # If the left is a variable then process it as such
            if isinstance(left, ast.Symbol):

                # Get the variable from function's scope
                dst_addr = self.objects[left.get_name()]

                # Store the value into targeted address
                src = self.coerce(right, dst_addr.type.over, node.right)
                src = self.check_copy_instead_move(src, node.right)
                self.builder.store(src.ir, dst_addr.ir)

            elif isinstance(left, flow.SetAttribute):

                # Visit the left value to get its IR object
                dst_addr = self.visit(left)

                # Store the value into targeted class attribute or list item
                src = self.coerce(right, dst_addr.type.over, node.right)
                src = self.check_copy_instead_move(src, node.right)
                self.builder.store(src.ir, dst_addr.ir)

            elif isinstance(left, flow.SetElement):

                # Visit the list to get its IR object
                obj = self.visit(left.obj)

                # Visit the key (ie the list's index to extract the element) to get its IR object
                key = self.visit(left.key)

                if types.unwrap(obj.type).name.startswith("data<"):

                    # Get address at given offset
                    if types.is_wrapped(obj.type):
                        loaded = self.builder.load(obj.ir)
                        obj = Value(obj.type.over, loaded)
                    dst_addr = Value(obj.type, self.builder.gep(obj.ir, [key.ir]))

                    # Store the value into targeted address
                    src = self.coerce(right, dst_addr.type.over, node.right)
                    src = self.check_copy_instead_move(src, node.right)
                    self.builder.store(src.ir, dst_addr.ir)

                elif types.unwrap(obj.type).name.startswith("tuple<"):

                    # Get value at given index
                    obj_type = types.unwrap(obj.type)
                    element_attribute = obj_type.attributes["element_" + str(left.key.literal)]
                    dst_addr = Value(types.Wrapper(element_attribute["type"]),
                                     self.builder.gep(obj.ir, [i32(0), i32(element_attribute["idx"])]))

                    # Store the value into targeted address
                    src = self.coerce(right, dst_addr.type, node.right)
                    src = self.check_copy_instead_move(src, node.right)
                    self.builder.store(src.ir, dst_addr.ir)

                else:

                    # Call the type's method used to set value to list's element
                    obj_type = types.unwrap(obj.type)
                    set_item_fn = obj_type.select(module=self.module, node=left.key, name="__setitem__",
                                                  positional=[None, key.type, right.type], named={})
                    key = self.coerce(key, set_item_fn.type.over["args"][1], left.key)
                    src = self.coerce(right, set_item_fn.type.over["args"][2], node.right)

                    self.builder.call(set_item_fn.ir, [obj.ir, key.ir, src.ir])

        # Visit the right expression to get its IR object
        value = self.visit(node.right)

        # If the right expression is a helper variable just holt it into scope
        if isinstance(node.left, ast.Symbol) and node.left.is_hidden():

            # Hold it into function's scope
            value = self.check_copy_instead_move(value, node.right)
            self.objects[node.left.get_name()] = value

        # Set the value for every element of the tuple
        elif isinstance(node.left, ast.Tuple):

            if types.is_reference(value.type):
                loaded = self.builder.load(value.ir)
                value = Value(value.type.over, loaded)
            tuple_type = types.unwrap(value.type)

            for i, element in enumerate(node.left.elements):

                # Get the memory address of the value at element's index
                attribute = tuple_type.attributes["element_" + str(i)]
                element_idx = attribute["idx"]
                element_type = attribute["type"]
                src_addr = self.builder.gep(value.ir, [i32(0), i32(element_idx)])

                # Load the value from memory
                src = Value(element_type, self.builder.load(src_addr))

                # Set element's value
                set_left_value(element, src)

        # Set the value of the single variable, class's attribute or list's item
        else:
            set_left_value(node.left, value)

    # Types

    def visit_as(self, node):

        # Visit the left expression to get its IR object
        # Cast the value to the type specified in the `as` node
        left = self.visit(node.left)
        left = self.coerce(left, node.type, node.left)

        return left

    def visit_isinstance(self, node):

        # Check if object is one of the types specified
        res = False
        for typ in node.types:
            if node.obj.type.name == typ.name:
                res = True
                break

        return Value(node.type, i1(1) if res else i1(0))

    def visit_sizeof(self, node):

        # Get the allocated size for the type specified
        size = self.sizeof(node.target_type.ir)

        return Value(node.type, node.type.ir(size))

    def visit_transmute(self, node):

        # Visit the object expression to get its IR object
        obj = self.visit(node.obj)

        # Bitcast the value to the type specified in the `transmute` node
        value = self.builder.bitcast(obj.ir, node.type.ir)

        return Value(node.type, value)

    # Memory manipulation

    def visit_init(self, node):
        typ = types.unwrap(node.type)

        # Check if `self` should survive/escape from a `__init__` call
        # In other words, whether the object should or not be freed after call, different memory allocations
        # should be used for each case
        if types.is_heap_owner(node.type):

            # Allocate `self` object into "heap" memory
            self_addr = self.heap_alloc(typ.ir, 1)

        else:

            # Allocate `self` object into "stack" memory
            typ = node.type if node.type.byval else typ
            self_addr = self.builder.alloca(typ.ir)

        # Generate and tore the object's ID into address of `id` attribute
        if "id" in typ.attributes:
            id = generate_object_id()
            id_idx = typ.attributes["id"]["idx"]
            id_addr = self.builder.gep(self_addr, [i32(0), i32(id_idx)])
            self.builder.store(integer(id), id_addr)

        return Value(node.type, self_addr)

    def check_del(self, obj, is_heap_owner):
        obj_type = types.unwrap(obj.type)

        # Free the object attributes
        for name, attribute in obj_type.attributes.items():
            attribute_type = attribute["type"]

            # Free the attribute itself
            if not attribute_type.byval and not types.is_reference(attribute_type):

                if not isinstance(attribute_type, types.Data):

                    if is_heap_owner or types.is_heap_owner(attribute_type):

                        # Get the memory address of the attribute based on its index in the object's class
                        attribute_addr = self.builder.gep(obj.ir, [i32(0), i32(attribute["idx"])])
                        attribute = self.builder.load(attribute_addr)
                        attr = Value(attribute_type, attribute)

                        self.check_del(attr, True)

                elif not attribute_type.over.byval:

                    # Create all the LLVM blocks to be used in the loop
                    free_array_condition_block = self.fn.ir.append_basic_block(name="free_array_condition")
                    free_array_free_element_block = self.fn.ir.append_basic_block(name="free_array_free_element")
                    free_array_exit_block = self.fn.ir.append_basic_block(name="free_array_exit")

                    # Initialize the counter
                    counter_addr = self.builder.alloca(integer)
                    self.builder.store(integer(0), counter_addr)

                    # Get array's 'len' attribute value
                    len_idx = obj_type.attributes["len"]["idx"]
                    len_addr = self.builder.gep(obj.ir, [i32(0), i32(len_idx)])
                    length = self.builder.load(len_addr)

                    # Get array's 'data' attribute value
                    data_idx = obj_type.attributes["data"]["idx"]
                    data_addr = self.builder.gep(obj.ir, [i32(0), i32(data_idx)])
                    data = self.builder.load(data_addr)

                    # Jump the execution to the condition analysis
                    self.builder.branch(free_array_condition_block)
                    self.builder = ir.IRBuilder(free_array_condition_block)

                    # Get the counter value
                    counter = self.builder.load(counter_addr)

                    # Generate the IR object for checking the loop condition and which block it should jump into,
                    # depending on its value.
                    is_counter_less_len = self.builder.icmp_signed("<", counter, length, name="is_counter_less_len")
                    self.builder.cbranch(is_counter_less_len, free_array_free_element_block, free_array_exit_block)

                    # Initialize the block to free the array element
                    self.builder = ir.IRBuilder(free_array_free_element_block)

                    # Get the element by its index, ie the counter
                    element_addr = self.builder.gep(data, [counter])
                    element = Value(attribute_type, element_addr)

                    self.check_del(element, True)

                    # Increment the counter
                    counter = self.builder.add(counter, integer(1))
                    self.builder.store(counter, counter_addr)

                    self.builder.branch(free_array_condition_block)
                    self.builder = ir.IRBuilder(free_array_exit_block)

        # Free the object (obviously if it is allocated in the "heap" memory)
        if is_heap_owner:

            # Visit the data object to get its IR object

            # Convert object pointer to bytes pointer for it be passed to 'free' function
            ptr = self.builder.bitcast(obj.ir, i8.as_pointer())

            # Call `free` function to release the object in the "heap" memory
            free_fn = self.module.symbols["free"].ir
            self.builder.call(free_fn, [ptr])

    def visit_del(self, node):
        assert not types.is_reference(node.obj.type)

        # TODO: Temporarily the freeing is disabled until all tests be successful

        # Visit the data object to get its IR object
        #obj = self.visit(node.obj)

        #self.check_del(obj, types.is_heap_owner(node.obj.type))

    def calculate_size(self, target_type, num_elements):
        size = self.sizeof(target_type)

        if isinstance(num_elements, int):
            total_size = integer(size * num_elements)
        elif isinstance(num_elements, ast.Int):
            total_size = integer(size * num_elements.literal)
        else:
            if not isinstance(num_elements, Value):
                num_elements = self.visit(num_elements)
            total_size = self.builder.mul(integer(size), num_elements.ir)

        return total_size

    def heap_alloc(self, target_type, num_elements, previous_allocation_ptr=None):

        # Calculate the total size based on type's size and the number of elements
        total_size = self.calculate_size(target_type, num_elements)

        # Call the allocation function to allocate (or resize the previous allocation) in the "heap" memory
        if previous_allocation_ptr is not None:
            realloc_fn = self.module.symbols["realloc"].ir
            bytes_ptr = self.builder.call(realloc_fn, [previous_allocation_ptr, total_size])
        else:
            alloc_fn = self.module.symbols["malloc"].ir
            bytes_ptr = self.builder.call(alloc_fn, [total_size])

        # Convert bytes pointer to target type pointer
        ptr = self.builder.bitcast(bytes_ptr, target_type.as_pointer())

        return ptr

    def visit_reallocmemory(self, node):

        # Visit the data object to get its IR object
        obj = self.visit(node.obj)

        # Unwrap the allocated data stored by the object
        if types.is_wrapped(obj.type):
            loaded = self.builder.load(obj.ir)
            obj = Value(obj.type.over, loaded)

        # Resizes the amount of "heap" memory for the data
        previous_allocation_ptr = self.builder.bitcast(obj.ir, i8.as_pointer())
        ptr = self.heap_alloc(node.type.over.ir, node.num_elements, previous_allocation_ptr)

        return Value(node.type, ptr)

    def manipulate_memory(self, node, fn_name):

        # Calculate the total size based on type's size and the number of elements
        total_size = self.calculate_size(node.src.type.over.ir, node.num_elements)

        # Convert source type pointer to bytes pointer
        src = self.visit(node.src)
        src_ptr = self.builder.bitcast(src.ir, i8.as_pointer())

        # Convert destiny type pointer to bytes pointer
        dst = self.visit(node.dst)
        dst_ptr = self.builder.bitcast(dst.ir, i8.as_pointer())

        # Call the function to copy or move data in the memory
        memory_fn = self.module.symbols[fn_name].ir
        self.builder.call(memory_fn, [dst_ptr, src_ptr, total_size, i32(1), i1(0)])

    def visit_copymemory(self, node):
        self.manipulate_memory(node, "llvm.memcpy.p0.p0.i" + str(self.word_size))

    def visit_movememory(self, node):
        self.manipulate_memory(node, "llvm.memmove.p0.p0.i" + str(self.word_size))

    def visit_reference(self, node):

        # Allocate "stack" memory to store the address of the referenced value
        if isinstance(node.value, ast.Symbol):
            value_addr = self.visit_symbol(node.value, dereference=False)
        else:
            value_addr = self.visit(node.value)
        ref_addr = self.builder.alloca(value_addr.type.ir)
        self.builder.store(value_addr.ir, ref_addr)

        return Value(node.type, ref_addr)

    def visit_dereference(self, node):

        # Unload from "stack" memory the referenced value
        reference = self.objects[node.value.get_name()]
        value = self.builder.load(self.builder.load(reference.ir))

        return Value(node.value.type.over, value)

    def visit_offset(self, node):

        # Visit the pointer object to get its IR object
        obj = self.visit(node.obj)

        # Visit the idx (ie the memory's position to extract the offset) to get its IR object
        idx = self.visit(node.idx)

        # Get the offset's address
        offset_addr = self.builder.gep(obj.ir, [idx.ir])

        return Value(node.type, offset_addr)

    # Declaration of symbols and types in module

    def declare_external_stuff(self):
        """
        Generate the declaration of external functions and types that were not declared in other modules
        """

        # Declare types and function for exception handling which are defined in `personality.cpp`
        unwind_exception = self.module.ir.context.get_identified_type("struct._Unwind_Exception")
        unwind_exception.elements = [i64,
                                     ir.FunctionType(void, [i32, unwind_exception.as_pointer()]).as_pointer(),
                                     i64, i64]
        unwind_context = self.module.ir.context.get_identified_type("struct._Unwind_Context")
        personality_fn = ir.Function(self.module.ir, ir.FunctionType(i32, [i32, i32, i64,
                                                                      unwind_exception.as_pointer(),
                                                                      unwind_context.as_pointer()]),
                                     name="__ragaz_personality")
        personality_fn.attributes.add("nounwind")
        personality_fn.attributes.add("ssp")
        personality_fn.attributes.add("uwtable")

    def declare_global(self, name, var, external=False):
        """
        Generate the declaration of a global variable used in this module.
        """
        var_type = types.unwrap(var.value.type)

        if var_type.name == "str":
            literal = var.value.literal
            length = len(literal)

            # Create the global variable to store the array's data of the string
            data_type_as_bytearray = ir.ArrayType(i8, length)
            data_addr = ir.GlobalVariable(self.module.ir, data_type_as_bytearray, name=var.get_name() + ".data")
            if not external:
                # Set the content of the array's data
                data_addr.initializer = ir.Constant(data_type_as_bytearray, bytearray(literal.encode("utf8")))
            data_addr = data_addr.bitcast(i8.as_pointer())

            # Create the global variable to store the array of the string
            array_type = types.unwrap(var_type.attributes["arr"]["type"])
            array_addr = ir.GlobalVariable(self.module.ir, array_type.ir, name=var.get_name() + ".array")
            if not external:
                # Set the content of the array
                array_addr.initializer = ir.Constant(array_type.ir, [generate_object_id(), length, data_addr])

            # Set value of the string (ie its bytes array)
            id = generate_object_id()
            value = [id, array_addr]
        else:
            # Set value of the literal (it can be a number, float, etc)
            value = var.value.literal

        # Create the global variable with type and value defined earlier
        var_addr = ir.GlobalVariable(self.module.ir, var_type.ir, name=var.get_name())
        if not external:
            # Set the content of the variable
            var_addr.initializer = ir.Constant(var_type.ir, value)

        # Hold the variable in the function's scope
        if types.is_wrapped(var.value.type):
            var_type = var.value.type
        else:
            var_type = types.Wrapper(var.value.type)
        self.objects[name] = Value(var_type, var_addr)

    def declare_type(self, typ, external=False):
        """
        Generate the declaration of a type used in this module.
        """

        # Declare the identified structured type
        attributes = sorted(typ.attributes.values(), key=lambda x: x["idx"])
        struct_type = self.module.ir.context.get_identified_type(typ.name)
        typ.ir = struct_type
        struct_type.elements = [attribute["type"].ir for attribute in attributes]

        # Declare the global variable to hold the structured type's size
        type_size = ir.GlobalVariable(self.module.ir, integer, name=(typ.name + ".size"))
        type_size.global_constant = True

        # Set value of the structured type's size if it's not set in other source
        if not external:
            abi_size = self.sizeof(struct_type)
            type_size.initializer = ir.Constant(integer, abi_size)

    def declare_trait(self, typ):
        """
        Generate the declaration of a trait used in this module.
        """

        # Create a wrap type to store the virtual methods of the trait and the pointer to the original object
        typ.ir = self.module.ir.context.get_identified_type(typ.name + ".wrap")

        # Get all virtual method types declared on this trait
        method_types = []
        for name, methods in sorted(typ.methods.items()):
            for fn in methods:

                # Replace the first argument (`self`) type to a bytes pointer; this is necessary because `self`
                # can receive values of different types, so it's better receive just the address of
                # the value (bytes pointer)
                args_types = list(fn.type.over["args"])
                args_types[0] = self.module.instance_type("&byte")

                ret_type = fn.type.over["ret"]

                fn_type = types.Function(ret_type, args_types)
                method_types.append(fn_type.ir)

        # Create a type to store the virtual methods of the trait
        trait_methods_type = self.module.ir.context.get_identified_type(typ.name + ".virtual_methods")
        trait_methods_type.elements = method_types

        # Finalize the wrap type setting the pointers to the virtual methods of the trait and the pointer to
        # the original object
        typ.ir.elements = [trait_methods_type.as_pointer(), i8.as_pointer()]

    def declare_function(self, node):
        """
        Generate the declaration of a function (just its signature not its definition).
        """

        if types.is_concrete(node):

            # If the function is 'main', then arguments as 'argc' and 'argv' must be inserted as part the function
            # even without the user explicitly them. Later it will be discarded as 'sys.argv' is created
            if node.get_name() == "main" and len(node.args) > 0:
                ret = node.type.over["ret"]
                argc = self.module.instance_type("i32")
                argv = self.module.instance_type("data<data<byte>>")
                fn_type = types.Function(ret, [argc, argv])
                args_names = ["argc", "argv"]
            else:
                fn_type = node.type
                args_names = [arg.name for arg in node.args]

            # Get the signature of the function (name, return type and args) if it exists else create a signature
            fn = ir.Function(self.module.ir, fn_type.ir.pointee, name=node.get_name())
            node.ir = fn

            # Name the function arguments
            for arg, name in zip(fn.args, args_names):
                arg.name = name

            # Hold the function in the function's scope
            # TODO: Change this to node.get_name()
            self.objects[node.name] = Value(fn_type, fn)

    # Main method

    def process_module(self):

        # Setup root scope
        self.objects = util.ScopesDict()

        # Define types and function for exception handling and other stuffs
        self.declare_external_stuff()

        # Declare global variables
        for name, global_ in self.module.symbols.all_modules().items():
            if isinstance(global_, module_.Global):
                self.declare_global(name, global_, external=not self.module.symbols.is_in_current_module(global_.name))

        # Determine type dependencies for all types that have to been defined
        dependencies = {}
        for name, typ in self.module.types.all_modules().items():

            def get_types(attribute_type):
                if types.is_wrapped(attribute_type):
                    return get_types(types.unwrap(attribute_type))
                elif isinstance(attribute_type, types.Data):
                    return get_types(attribute_type.over)
                elif isinstance(attribute_type, types.Function):
                    function_types = get_types(attribute_type.over["ret"])
                    for arg_type in attribute_type.over["args"]:
                        function_types.update(get_types(arg_type))
                    return function_types
                elif attribute_type.name != typ.name and attribute_type.name not in types.BASIC:
                    return {attribute_type.name}
                else:
                    return set()

            # Ignore basic types like `void`, `i8`, `float`, etc. (intrinsically defined by LLVM)
            # Anything else must be declared
            must_declare = isinstance(typ, types.Base) and types.is_concrete(typ) and typ.name not in types.BASIC

            # Determine type dependencies for the type's attributes
            if must_declare:
                dependencies[typ.name] = set()
                for attribute in typ.attributes.values():
                    dependencies[typ.name].update(get_types(attribute["type"]))

        # Traverse all type dependencies to create a unified list of types to declare
        remains = set(dependencies)
        types_to_declare = []
        while len(remains) > 0:

            # Write out types with no dependencies
            done = set()
            for name in remains:
                if len(dependencies[name]) == 0:
                    types_to_declare.append(self.module.types[name])
                    done.add(name)

            # Remove the processed types from dependency lists
            remains -= {name for name in done}
            for remain_type in remains:
                for done_type in done:
                    if done_type in dependencies[remain_type]:
                        dependencies[remain_type].remove(done_type)

            assert len(done) > 0, len(remains) > 0  # check that we made progress

        # Declare types
        for typ in types_to_declare:
            self.declare_type(typ, external=not self.module.types.is_in_current_module(typ.name))

        # Declare traits
        for name, trait in self.module.types.all_modules().items():
            if isinstance(trait, types.Trait) and types.is_concrete(trait):
                self.declare_trait(trait)

        # Declare all type methods
        for name, typ in self.module.types.all_modules().items():
            # Don't declare methods of `anyint` and `anyfloat` because they use the same methods as default integer
            # and default float types; this will avoid duplicate declaration for a same method
            if isinstance(typ, types.Base) and types.is_concrete(typ):
                for methods in typ.methods.values():
                    for method in methods:
                        self.declare_function(method)

        # Declare functions
        for name, fn in self.module.symbols.all_modules().items():
            if isinstance(fn, ast.Function):
                self.declare_function(fn)

        # Once all the IR signature of the functions were gathered, their internal code is visited
        for fn in self.module.functions:
            self.visit_function(fn)


def generate_module_ir(target_machine, module):
    word_size = types.WORD_SIZE
    generator = CodeGenerator(target_machine, word_size)
    module_ir = generator.generate(module)
    module_ir_str = str(module_ir)
    llvm.parse_assembly(module_ir_str).verify()
    return module_ir
