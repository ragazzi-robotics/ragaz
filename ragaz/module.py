import os
from ragaz import ast_ as ast, types_ as types, util
from ragaz.ast_passes import implicits


class Global(util.Repr):

    def __init__(self, pos, name, internal_name, value):
        self.pos = pos
        self.name = name
        self.internal_name = internal_name
        self.value = value

    def get_name(self):
        return self.internal_name if self.internal_name is not None else self.name


class TypeAlias(object):

    def __init__(self, name, node):
        self.name = name
        self.target_type = node


class Scope(object):
    """
    This class is used to store all types (basic ones like integer or string, or structured ones like classes,
    tuples, etc) visible only to a given module.
    """

    def __init__(self, current_module, builtin_module, builtin_items):
        self.current_module = current_module
        self.builtin_module = builtin_module
        self.builtin_items = builtin_items
        self.current_itens = {}
        self.imported_modules = {}

    def find_item(self, key, error_if_not_found=False):
        if key in self.current_itens:
            return self.current_itens[key]
        elif self.builtin_items is not None and key in self.builtin_items:
            return self.builtin_items[key]
        else:
            for items, objects in self.imported_modules.items():
                for alias, name in objects:
                    if alias == key:
                        return items[name]
            if error_if_not_found:
                assert False, "'{key}' not found".format(key=key)
            else:
                return None

    def __contains__(self, key):
        item = self.find_item(key)
        return item is not None

    def __getitem__(self, key):
        item = self.find_item(key, error_if_not_found=True)
        return item

    def __setitem__(self, key, value):
        self.current_itens[key] = value

    def get(self, key, default=None):
        item = self.find_item(key)
        if item is not None:
            return item
        else:
            return default

    def all_modules(self):
        full = {}
        if self.builtin_items is not None:
            full.update(self.builtin_items.all_modules())
        full.update(self.current_itens)
        for items, objects in self.imported_modules.items():
            for alias, name in objects:
                full[alias] = items[name]
        return full

    def is_in_current_module(self, key):
        return key in self.current_itens


class Module(object):
    """
    A ``Module`` class contain a mapping from symbols to language-level things:
    - an object imported from another module,
    - a class,
    - a function,
    - a trait,
    - a global variable
    """

    def __init__(self, file, node, builtin_module=None, is_core=False):

        # Source file which this module is related
        self.file = file

        # Name this module top the relative path of the file. Example:
        #
        #   \home\someuser\projects\someproject\test\test1.zz -> \test\test1
        #
        # This is useful for we give unique name to types, functions, globals, etc.
        if is_core:
            self.name = "Ragaz.core"
        else:
            file_without_extension = os.path.splitext(file)[0]
            file_without_base_dir = file_without_extension.removeprefix(util.BASE)
            file_without_slashes = file_without_base_dir.replace(".", "_").replace("/", ".")
            self.name = "Ragaz" + file_without_slashes

        # To flag when a module is the core of the language which include runtime and builtin functions
        self.is_core = is_core

        # Counter for create new names
        self.suffix_count = 0

        # Store the module which call this module
        self.builtin_module = builtin_module

        # List of passes processors created for this module
        self.processors = {}

        # List of function nodes of the module which the first element is the name and the second element is
        # the function/method
        self.functions = []

        # Store names and nodes of the classes, functions, global variables, etc, defined in this module or imported
        # by it
        if builtin_module is not None:
            builtin_symbols = builtin_module.symbols
        else:
            builtin_symbols = None
        self.symbols = Scope(self, builtin_module, builtin_symbols)

        # Store all types (basic ones like integer or string, or structured ones like classes, tuples, etc) visible
        # only in this module
        if builtin_module is not None:
            builtin_types = builtin_module.types
        else:
            builtin_types = None
        self.types = Scope(self, builtin_module, builtin_types)

        # Store the LLVM IR module generated for this module
        self.ir = None

        # Collect symbols (variables, classes instances, functions, global variables, etc), defined in this module or
        # imported by it
        self.collect_symbols(node)

    def __repr__(self):
        contents = sorted(util.items(self.__dict__))
        show = ("{attribute}={content}".format(attribute=attribute, content=content) for (attribute, content) in contents)
        return "<{cls}({attributes})>".format(cls=self.__class__.__name__, attributes=", ".join(show))

    def generate_suffix(self):
        self.suffix_count += 1
        return "${suffix}".format(suffix=self.suffix_count - 1)

    def check_same_length(self, tuple1, tuple2):
        """
        Checks if two tuples are the same size and if so, points to the first extra item.
        """
        extra_item = None
        diff = len(tuple1) - len(tuple2)
        if diff > 0:
            extra_item = tuple1[len(tuple2)]
        elif diff < 0:
            extra_item = tuple2[len(tuple1)]
        if extra_item is not None:
            msg = (extra_item.pos, "extra item found in assignment")
            raise util.Error([msg])

    def instance_type(self, typ, translations={}):
        """
        This function is used both to return the instance of a type (usually when required in the form of a string)
        or to create it if it doesn't already exist and finally return it (as is the case with types for tuples,
        lists, iterables, etc.)
        """

        # Void
        if typ is None:
            typ = self.instance_type("void")

        # Variadic arguments
        elif isinstance(typ, ast.VariadicArgs):
            typ = types.VariadicArgs()

        # Mutable type
        elif isinstance(typ, ast.Mutable):
            typ = self.instance_type(typ.value, translations=translations)
            typ.is_mutable = True
            typ = typ

        # Reference to an address in the stack
        elif isinstance(typ, ast.Reference) or (isinstance(typ, str) and typ[0] == "&"):
            if isinstance(typ, ast.Reference):
                wrapped_type = typ.value
            else:
                wrapped_type = typ[1:]
            typ = types.Wrapper(self.instance_type(wrapped_type, translations=translations), is_reference=True)

        # Type derived from a template like list<T>, etc.
        elif isinstance(typ, ast.DerivedType) or (isinstance(typ, str) and "<" in typ):
            if isinstance(typ, ast.DerivedType):
                template_name, derivation_types = typ.name, typ.types
            else:
                ext = typ.partition("<")
                template_name = ext[0]
                derivation_types = ext[2][:-1].split(", ")
            if template_name == "data":
                typ = types.Data(self.instance_type(derivation_types[0], translations=translations))
            else:
                template = self.symbols.get(template_name, None)
                if template is not None:
                    derivation_types = [self.instance_type(tp, translations=translations) for tp in derivation_types]
                    typ = types.get_derived_type(self, template, False, derivation_types)
                else:
                    msg = (typ.pos, "type '{type}' was not found".format(type=template_name))
                    hints = ["Check whether there is a typo in the name.",
                             "Have you forgotten to define it or import it?"]
                    raise util.Error([msg], hints=hints)

        # Function type (callable type)
        elif isinstance(typ, ast.FunctionType):
            typ = types.Function(self.instance_type(typ.ret_type, translations=translations),
                                 [self.instance_type(typ.type, translations=translations) for typ in typ.args_types])

        # Handle any other type not handled above
        elif isinstance(typ, ast.Type) or isinstance(typ, str):
            if isinstance(typ, ast.Type):
                type_name = typ.name
            else:
                type_name = typ

            # Replace the type to its alias specified in the translations. For instance:
            #   T -> int
            if type_name in translations:
                typ = translations[type_name]

            # Return the type previously added to the module
            elif type_name in self.types:
                typ = self.types[type_name]

                # Return the actual type behind the alias
                if isinstance(typ, TypeAlias):
                    typ = self.instance_type(typ.target_type, translations=translations)

            else:
                msg = (typ.pos, "type '{type}' was not found".format(type=type_name))
                hints = ["Check whether there is a typo in the name.",
                         "Have you forgotten to define it or import it?"]
                raise util.Error([msg], hints=hints)

        # Already it's a type, just ignore it
        elif isinstance(typ, types.Base):
            pass

        else:
            assert False, "No type {type}".format(type=typ)

        return typ

    def collect_symbols(self, node):
        """
        Collect symbols (variables, classes instances, functions, global variables, etc), defined in this module or
        imported by it
        """

        def create_global(pos, name, value):
            internal_name = "{module}.{name}".format(module=self.name, name=name)
            return Global(pos, name, internal_name, value)

        # Traverse all statements from AST module node to append class, functions, global variables, etc
        for n in node.suite:

            # Appends an object imported from another module to this module block
            if isinstance(n, ast.Import):
                self.symbols["import_" + self.generate_suffix()] = n

            # Appends global variables to this module block
            elif isinstance(n, ast.VariableDeclaration):
                for declaration in implicits.decompose_variable_declaration(n):
                    declaration.assignment.right.type = declaration.assignment.left.type
                    self.symbols[declaration.variables.name] = create_global(declaration.pos,
                                                                             declaration.assignment.left.name,
                                                                             declaration.assignment.right)

            # Appends type aliases this module block
            elif isinstance(n, ast.SetTypeAliases):
                self.check_same_length(n.aliases, n.types)
                for alias, typ in zip(n.aliases, n.types):
                    self.symbols[alias.name] = TypeAlias(alias.name, typ)

            # Appends a class and its methods to this module block
            elif isinstance(n, ast.Class):
                self.symbols[n.name] = n

                for method in n.methods:

                    if method.name != "__new__":
                        if len(method.args) == 0:
                            msg = (method.pos, "missing 'self' argument")
                            raise util.Error([msg])
                        elif method.args[0].name != "self":
                            msg = (method.args[0].pos, "first method argument must be called 'self'")
                            raise util.Error([msg])

                    # Check for duplicate type_vars in the method
                    if len(n.type_vars) > 0 and len(method.type_vars) > 0:
                        for type_name in method.type_vars:
                            if type_name in n.type_vars:
                                existent_type_var = n.type_vars[type_name]
                                duplicated_type_var = method.type_vars[type_name]
                                msg = (existent_type_var.pos, "type '{type}' already was declared in the class"
                                       .format(type=type_name))
                                msg2 = (duplicated_type_var.pos, "but method tries declare it again")
                                raise util.Error([msg, msg2])

                    method.self_type = n
                    self.functions.append(method)

            # Appends a trait to this module block
            elif isinstance(n, ast.Trait):
                self.symbols[n.name] = n

            # Appends a function declaration or definition to this module block
            elif isinstance(n, ast.Function):
                if self.is_core and n.name.startswith("llvm_"):
                    n.name = n.name.replace("_", ".")
                self.symbols[n.name] = n
                if n.suite is not None:
                    self.functions.append(n)

            # Ignore multiline strings
            elif isinstance(n, ast.MultilineString):
                pass

            else:
                assert False, "Not allowed here: {node}".format(node=n)
