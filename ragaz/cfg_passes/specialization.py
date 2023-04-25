"""
This pass specializes all types set to 'anyint' or 'anyfloat' in 'typing' pass.

This specialization is based on context which the node is.

In the example bellow, the 'specialization' pass still was not used:

    var a = 1  # No specific type, thus 'a' -> 'anyint'
    var b: i32 = a  # 'b' -> 'i32'

With the 'specialization' process, as the analysis is done from bottom to top, the concrete type of 'a' is inferred from
its later assignment to 'b':

    var a = 1
    var b: i32 = a  # 'a' becomes 'i32'

This happens because all non-specialized types in the 'right' side of the assignmnent will be specialized using
the type of 'left' side (i.e the variable) as base.

The same goes when a non-specialized node is passed as argument or return of a function: the formal type of the
argument or return of the function is used as base to replace 'anyint' or 'anyfloat' of the node.

When it is not possible infer the concrete type from destination, the node will be specialized either to 'int' (if
'anyint') or to 'float' (if 'anyfloat') once they are default-sized types according to the target architecture.
"""

from ragaz import ast_ as ast, types_ as types, util
from ragaz.cfg_passes import typing

PASS_NAME = __name__.split(".")[-1]


class Specializer(object):

    def __init__(self, module):
        self.module = module
        self.fn = None

    def process(self):

        for fn in self.module.functions:
            self.visit_function(fn)

    def specialize(self, src_type, dst_type):
        """
        This used to replace a generic integer ("anyint") or float ("anyfloat") to a number with defined size (i8, i32,
        double, etc).
        """
        if types.is_wrapped(src_type):
            Wrapper = src_type.__class__
        else:
            Wrapper = None
        unwrapped_src_type = types.unwrap(src_type)

        dst_type = types.unwrap(dst_type)
        if dst_type is not None and (self.is_generic(dst_type) or isinstance(dst_type, types.Trait)):
            dst_type = None

        if unwrapped_src_type.name in ["anytype", "anyint", "anyfloat"]:
            if dst_type is None:
                if unwrapped_src_type == self.module.instance_type("anyint"):
                    dst_type = self.module.instance_type("int")
                elif unwrapped_src_type == self.module.instance_type("anyfloat"):
                    dst_type = self.module.instance_type("float")
                elif unwrapped_src_type == self.module.instance_type("anytype"):
                    assert False, "No type was specified to specialize"
            if Wrapper is not None:
                dst_type = Wrapper(dst_type)
        elif hasattr(unwrapped_src_type, "elements"):
            typ_name = unwrapped_src_type.name.partition("<")[0]
            element_types = []
            for i, element_type in enumerate(unwrapped_src_type.elements):
                dst_type_element = dst_type.elements[i] if dst_type is not None else None
                typ = self.specialize(unwrapped_src_type.elements[i], dst_type_element)
                element_types.append(typ)
            dst_type = self.module.instance_type(ast.DerivedType(None, typ_name, element_types),
                                                 translations=self.translations)
            if Wrapper is not None:
                dst_type = Wrapper(dst_type)
        elif dst_type is None or unwrapped_src_type == dst_type:
            dst_type = src_type
        else:
            assert False, "Cannot specialize {type} into {dst_type}".format(type=src_type, dst_type=dst_type)

        if Wrapper is not None:
            dst_type.is_heap_owner = src_type.is_heap_owner
            dst_type.is_reference = src_type.is_reference
            dst_type.is_mutable = src_type.is_mutable

        return dst_type

    def is_generic(self, typ, generic_types=["anytype", "anyint", "anyfloat"]):
        """
        Check if type have a generic integer or float that still wasn't converted to a type with specific size like
        i8, i32, double, etc. This conversion is made by the `specialize` pass.
        """
        typ = types.unwrap(typ)

        if hasattr(typ, "elements"):
            is_non_specialized = any([self.is_generic(tp, generic_types) for tp in typ.elements])
            if is_non_specialized:
                typ.is_non_specialized = is_non_specialized
            return is_non_specialized

        elif isinstance(typ, types.Data):
            is_non_specialized = self.is_generic(typ.over, generic_types)
            if is_non_specialized:
                typ.is_non_specialized = is_non_specialized
            return is_non_specialized

        else:
            is_non_specialized = typ.name in generic_types
            if is_non_specialized:
                typ.is_non_specialized = is_non_specialized
            return is_non_specialized

    def is_anytype(self, typ):
        return self.is_generic(typ, generic_types=["anytype"])

    def visit(self, node, typ=None):
        """
        This is used for call the proper visit method for a node. If node, for instance, is an ast.String, then
        this method will call `visit_string` method to handle the node properly.
        """
        fn_name = "visit_" + str(node.__class__.__name__).lower()
        visit_node_fn = getattr(self, fn_name)
        visit_node_fn(node, typ)

    # Node visitation methods

    def visit_function(self, fn):
        """
        Start the analysis.
        """
        util.check_previous_pass(self.module, fn, PASS_NAME)
        if PASS_NAME not in fn.passes:

            # Check if the function is derived for non-specialized integers or floats
            if fn.self_type is not None and self.is_generic(fn.self_type):
                fn.is_non_specialized = True
            else:
                for _, derived_type in fn.get_all_type_vars().items():
                    if self.is_generic(derived_type):
                        fn.is_non_specialized = True
                        break

            if types.is_concrete(fn):
                self.fn = fn

                # Set the module to translate types based on these 'type_vars'
                translations = {}
                translations.update(fn.get_all_type_vars())
                if fn.self_type is not None:
                    translations["Self"] = fn.self_type
                self.translations = translations

                for block in sorted(self.fn.flow.blocks, key=lambda blk: blk.id, reverse=True):
                    for step in sorted(block.steps, key=lambda stp: stp.id, reverse=True):
                        self.visit(step)

        fn.passes.append(PASS_NAME)

    def visit_beginscope(self, node, typ=None):
        pass

    def visit_endscope(self, node, typ=None):
        pass

    def unary_op(self, node, typ):
        self.visit(node.value, typ)
        node.type = node.value.type

    def binary_op(self, node, typ):
        if self.is_generic(node.left.type) and self.is_generic(node.right.type):
            self.visit(node.left)
            self.visit(node.right)
        elif self.is_generic(node.left.type):
            self.visit(node.left, node.right.type)
            self.visit(node.right)
        elif self.is_generic(node.right.type):
            self.visit(node.right, node.left.type)
            self.visit(node.left)

    # Basic types

    def visit_noneval(self, node, typ=None):
        node.type = typ

    def visit_bool(self, node, typ=None):
        pass

    def visit_int(self, node, typ=None):
        if typ in types.FLOATS:
            node.type = typ
            node.literal = float(node.literal)
        node.type = self.specialize(node.type, typ)

    def visit_float(self, node, typ=None):
        if typ in types.INTEGERS:
            node.type = typ
            node.literal = round(node.literal)
        node.type = self.specialize(node.type, typ)

    def visit_byte(self, node, typ=None):
        pass

    # Structure

    def visit_array(self, node, typ=None):
        self.visit(node.num_elements)
        if node.num_elements.type not in types.INTEGERS:
            msg = (node.num_elements.pos, "number of elements must be a value of integer type ('{type}' not allowed)"
                   .format(type=node.num_elements.type.name))
            hints = ["Use 'as' keyword to convert values.",
                     "Create a magic method to convert implicitly the values."]
            raise util.Error([msg], hints=hints)

    def visit_string(self, node, typ=None):
        pass

    def visit_tuple(self, node, typ=None):

        if self.is_generic(node.type):
            element_types = []
            for i, element_type in enumerate(types.unwrap(node.type).elements):
                if self.is_generic(element_type):
                    if typ is not None and not self.is_generic(typ):
                        is_reference_to_tuple = types.is_reference(typ)
                        right_type = types.unwrap(typ).elements[i]
                        if is_reference_to_tuple:
                            right_type = types.Wrapper(right_type, is_reference=True)
                        element_type = self.specialize(element_type, right_type)
                    else:
                        element_type = self.specialize(element_type, None)
                element_types.append(element_type)

            # Finally update the type of list with the element type found after specialization
            base_type = self.module.instance_type(ast.DerivedType(None, "tuple", element_types),
                                                  translations=self.translations)
            node.type = self.specialize(node.type, base_type)

        # Now specialize all elements using the specialized type as base in case of generics
        for i, element in enumerate(node.elements):
            if self.is_generic(element.type):
                self.visit(element, types.unwrap(node.type).elements[i])

    def visit_list(self, node, typ=None):

        if self.is_generic(node.type):
            if typ is None and self.is_anytype(node.type.over.elements[0]):
                msg = (node.pos, "no type was specified for the collection")
                hints = ["Declare the collection using the ': list<sometype>' syntax."]
                raise util.Error([msg], hints=hints)
            elif typ is not None and not self.is_generic(typ.over.elements[0]):
                element_type = typ.over.elements[0]
            else:
                # Get the elements' type of the list if no one was passed
                element_type = None
                for element in node.elements:
                    if element_type is None:
                        element_type = element.type
                    else:
                        element_type = types.choose_bigger_type(element_type, element.type)

            # Finally update the type of list with the element type found after specialization
            base_type = self.module.instance_type(ast.DerivedType(None, "list", [element_type]),
                                                  translations=self.translations)
            node.type = self.specialize(node.type, base_type)

        # Now specialize all elements using the specialized type as base in case of generics
        for element in node.elements:
            if self.is_generic(element.type):
                self.visit(element, node.type.over.elements[0])

    def visit_dict(self, node, typ=None):

        def specialize_element(idx, elements):
            if typ is not None and not self.is_generic(typ.over.elements[idx]):
                element_type = typ.over.elements[idx]
            else:
                # Get the elements' type of the set if no one was passed
                element_type = None
                for element in elements:
                    if element_type is None:
                        element_type = element.type
                    else:
                        element_type = types.choose_bigger_type(element_type, element.type)
            return element_type

        if self.is_generic(node.type):
            key_type = specialize_element(0, node.elements.keys())
            value_type = specialize_element(1, node.elements.values())

            # Finally update the type of dict with the key and value types found after specialization
            base_type = self.module.instance_type(ast.DerivedType(None, "dict", [key_type, value_type]),
                                                  translations=self.translations)
            node.type = self.specialize(node.type, base_type)

        # Now specialize all dict elements using the specialized type as base in case of generics
        for key, value in node.elements.items():
            if self.is_generic(key.type):
                self.visit(key, node.type.over.elements[0])
            if self.is_generic(value.type):
                self.visit(value, node.type.over.elements[1])

    def visit_set(self, node, typ=None):

        if self.is_generic(node.type):
            if typ is not None and not self.is_generic(typ.over.elements[0]):
                element_type = typ.over.elements[0]
            else:
                # Get the elements' type of the set if no one was passed
                element_type = None
                for element in node.elements:
                    if element_type is None:
                        element_type = element.type
                    else:
                        element_type = types.choose_bigger_type(element_type, element.type)

            # Finally update the type of set with the element type found after specialization
            base_type = self.module.instance_type(ast.DerivedType(None, "set", [element_type]),
                                                  translations=self.translations)
            node.type = self.specialize(node.type, base_type)

        # Now specialize all elements using the specialized type as base in case of generics
        for element in node.elements:
            if self.is_generic(element.type):
                self.visit(element, node.type.over.elements[0])

    def visit_attribute(self, node, typ=None):
        self.visit(node.obj)

        if self.is_generic(node.type):
            attribute = types.unwrap(node.obj.type).attributes[node.attribute]
            if self.is_generic(attribute["type"]):
                node.type = attribute["type"] = self.specialize(node.type, typ)

    def visit_setattribute(self, node, typ=None):
        self.visit_attribute(node, typ)

    def visit_element(self, node, typ=None):
        self.visit(node.obj)
        self.visit(node.key)
        if self.is_generic(node.type):
            if node.obj.type.name.startswith("data<"):
                node.type = self.specialize(node.type, node.obj.type.over)
            elif node.obj.type.name.startswith("tuple<"):
                node.type = self.specialize(node.type, node.obj.type.over.elements[node.key.literal + 1])
            elif node.obj.type.name.startswith("dict<"):
                node.type = self.specialize(node.type, node.obj.type.over.elements[1])
            else:
                node.type = self.specialize(node.type, node.obj.type.over.elements[0])

    def visit_setelement(self, node, typ=None):
        self.visit_element(node)

    # Boolean operators

    def visit_not(self, node, typ=None):
        self.unary_op(node, typ)

    def boolean(self, node):
        self.visit(node.left)
        self.visit(node.right)

    def visit_and(self, node, typ=None):
        self.boolean(node)

    def visit_or(self, node, typ=None):
        self.boolean(node)

    # Comparison operators

    def visit_is(self, node, typ=None):
        self.visit(node.left)

    def compare(self, node, typ):
        self.binary_op(node, typ)

    def visit_equal(self, node, typ=None):
        self.compare(node, typ)

    def visit_notequal(self, node, typ=None):
        self.compare(node, typ)

    def visit_lowerthan(self, node, typ=None):
        self.compare(node, typ)

    def visit_lowerequal(self, node, typ=None):
        self.compare(node, typ)

    def visit_greaterthan(self, node, typ=None):
        self.compare(node, typ)

    def visit_greaterequal(self, node, typ=None):
        self.compare(node, typ)

    # Arithmetic operators

    def arith(self, node, typ):
        self.binary_op(node, typ)

    def visit_neg(self, node, typ=None):

        # Check if this operation is involving signed numbers
        if self.is_generic(node.value.type):
            value_type = typ
        else:
            value_type = node.value.type
        if not types.BASIC[value_type.name]["signed"]:
            msg = (node.pos, "cannot use negate operation with unsigned numbers")
            raise util.Error([msg])

        self.unary_op(node, typ)

    def visit_add(self, node, typ=None):
        self.arith(node, typ)

    def visit_sub(self, node, typ=None):
        self.arith(node, typ)

    def visit_mod(self, node, typ=None):
        self.arith(node, typ)

    def visit_mul(self, node, typ=None):
        self.arith(node, typ)

    def visit_div(self, node, typ=None):
        self.arith(node, typ)

    def visit_floordiv(self, node, typ=None):
        self.arith(node, typ)

    def visit_pow(self, node, typ=None):
        self.arith(node, typ)

    # Bitwise operators

    def bitwise(self, node, typ):
        self.binary_op(node, typ)

    def visit_bwnot(self, node, typ=None):
        self.unary_op(node, typ)

    def visit_bwand(self, node, typ=None):
        self.bitwise(node, typ)

    def visit_bwor(self, node, typ=None):
        self.bitwise(node, typ)

    def visit_bwxor(self, node, typ=None):
        self.bitwise(node, typ)

    def visit_bwshiftleft(self, node, typ=None):
        self.bitwise(node, typ)

    def visit_bwshiftright(self, node, typ=None):
        self.bitwise(node, typ)

    # Control flow

    def visit_pass(self, node, typ=None):
        pass

    def visit_branch(self, node, typ=None):
        pass

    def visit_condbranch(self, node, typ=None):
        self.visit(node.cond, self.module.instance_type("ToBool"))

    def visit_phi(self, node, typ=None):
        left = node.left[1]
        right = node.right[1]

        self.visit(left, typ)
        self.visit(right, typ)

    def visit_raise(self, node, typ=None):
        pass

    def visit_landingpad(self, node, typ=None):
        pass

    def visit_resume(self, node, typ=None):
        pass

    def visit_call(self, node, typ=None):

        # Specialize the function in case of it be derived from generic numbers. This happens when the type_vars
        # translations are inferred from call's args
        positional, named = typing.organize_args(node.args)
        if isinstance(node.fn, ast.Function):
            fn_is_generic = any([self.is_generic(typ) for typ in node.fn.get_all_type_vars().values()])
            if fn_is_generic:

                # Get the derived types to create the function
                derivation_types = []
                for i, arg in enumerate(node.args):
                    actual_type = arg.type
                    formal_type = node.fn.type.over["args"][i]
                    if self.is_generic(formal_type):
                        if self.is_generic(actual_type):
                            specialized_type = self.specialize(actual_type, None)
                        else:
                            specialized_type = actual_type
                    else:
                        specialized_type = formal_type
                    derivation_types.append(types.unwrap(specialized_type))

                if isinstance(node.callable, ast.Attribute):

                    # Get the object type
                    obj = node.callable.obj
                    self.visit(obj)
                    obj_type = types.unwrap(obj.type)
                else:
                    obj_type = None

                # Calling a function or method:
                #     res = function()
                if isinstance(node.callable_object, ast.Function):
                    if obj_type is not None:
                        derivation_types = derivation_types[1:]  # Remove self type
                        node.callable_object = obj_type.select(self.module, node, node.callable.attribute, positional,
                                                               named)
                    node.fn = types.get_function(self.module, node.callable_object, True, derivation_types,
                                                 positional, named, self_type=obj_type)
                    node.type = node.fn.type.over["ret"]

                    # Update the object as 'self' argument
                    if obj_type is not None:
                        node.args[0] = obj

                # Calling a type constructor:
                #     res = Class()
                elif isinstance(node.callable_object, (ast.Class, types.Base)):

                    # Update '$parent_self' argument in method generator
                    is_method_as_generator = "." in node.callable_object.name
                    if is_method_as_generator:
                        parent_self_types = list(obj_type.type_vars.values())  # Get the $parent_self derivation types
                        derivation_types = derivation_types[:-1]  # Remove $parent_self argument type
                        derivation_types = derivation_types + parent_self_types
                        node.args[-1] = obj
                        positional[-1] = obj.type

                    derivation_types = derivation_types[1:]  # Remove self type
                    node.fn = types.get_constructor(self.module, node, node.callable_object, True, derivation_types,
                                                    positional, named, is_method_as_generator=is_method_as_generator)

                    # Insert `self` as the first argument
                    node.type.over = node.fn.self_type
                    if node.fn.name == "__init__":
                        node.args[0].type = node.type

        # Specialize the call arguments to the formal types of the called function
        formal_args_types = node.fn.type.over["args"]
        for i, arg in enumerate(node.args):
            self.visit(arg, formal_args_types[i])

    def visit_yield(self, node, typ=None):
        if node.value is not None:
            # Set the actual yield type to the formal yield type if generic
            self.visit(node.value, self.fn.type.over["ret"])

    def visit_return(self, node, typ=None):
        if node.value is not None:
            # Set the actual return type to the formal return type if generic
            self.visit(node.value, self.fn.type.over["ret"])

    # Symbols

    def visit_symbol(self, node, typ=None):
        if self.is_generic(node.type):
            node.type = self.specialize(node.type, typ)

    def visit_namedarg(self, node):
        self.visit(node.value)

    def visit_variabledeclaration(self, node, typ=None):
        if node.variables.type is not None and self.is_generic(node.variables.type):
            if node.assignment is not None:
                self.visit(node.assignment)
                right_type = node.assignment.left.type
            else:
                right_type = None

            # Specialize the type for every variable
            if isinstance(node.variables, ast.Tuple):
                for i, var in enumerate(node.variables.elements):
                    self.visit(var, right_type.over.elements[i])

            # Specialize the type of the single variable
            else:
                self.visit(node.variables, right_type)

    def visit_assign(self, node, typ=None):
        if self.is_generic(node.left.type):
            self.visit(node.right)
            self.visit(node.left, node.right.type)
        else:
            self.visit(node.left)
            self.visit(node.right, node.left.type)

    # Types

    def visit_as(self, node, typ=None):
        if self.is_generic(node.left.type):
            self.visit(node.left, node.type)

    def visit_isinstance(self, node, typ=None):
        self.visit(node.obj)

    def visit_sizeof(self, node, typ=None):
        if self.is_generic(node.type):
            node.type = self.specialize(node.type, typ)

    def visit_transmute(self, node, typ=None):
        self.visit(node.obj)
        if self.is_generic(node.type):
            node.type = self.specialize(node.type, typ)

    # Memory manipulation

    def visit_init(self, node, typ=None):
        pass

    def visit_del(self, node, typ=None):
        self.visit(node.obj)

    def visit_reallocmemory(self, node, typ=None):
        self.visit(node.obj)
        self.visit(node.num_elements)
        if node.num_elements.type not in types.INTEGERS:
            msg = (node.num_elements.pos, "number of elements must be a value of integer type ('{type}' not allowed)"
                   .format(type=node.num_elements.type.name))
            hints = ["Use 'as' keyword to convert values.",
                     "Create a magic method to convert implicitly the values."]
            raise util.Error([msg], hints=hints)

    def visit_copymemory(self, node, typ=None):
        self.visit(node.src)
        self.visit(node.dst)
        self.visit(node.num_elements)
        if node.num_elements.type not in types.INTEGERS:
            msg = (node.num_elements.pos, "number of elements must be a value of integer type ('{type}' not allowed)"
                   .format(type=node.num_elements.type.name))
            hints = ["Use 'as' keyword to convert values.",
                     "Create a magic method to convert implicitly the values."]
            raise util.Error([msg], hints=hints)

    def visit_movememory(self, node, typ=None):
        self.visit(node.src)
        self.visit(node.dst)
        self.visit(node.num_elements)
        if node.num_elements.type not in types.INTEGERS:
            msg = (node.num_elements.pos, "number of elements must be a value of integer type ('{type}' not allowed)"
                   .format(type=node.num_elements.type.name))
            hints = ["Use 'as' keyword to convert values.",
                     "Create a magic method to convert implicitly the values."]
            raise util.Error([msg], hints=hints)

    def visit_reference(self, node, typ=None):
        self.visit(node.value, typ)
        node.type.over = node.value.type

    def visit_dereference(self, node, typ=None):
        self.visit(node.value, typ)
        node.type = node.value.type.over

    def visit_offset(self, node, typ=None):
        self.visit(node.obj)
        self.visit(node.idx)
        if self.is_generic(node.type):
            node.type = self.specialize(node.type, typ)
