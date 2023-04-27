import llvmlite.binding as llvm
import os
import subprocess
import collections
from ragaz import ast_ as ast, parser, module as module_, util
from ragaz.ast_passes import expressions, implicits, flow
from ragaz.cfg_passes import uses, typing, specialization, escapes, destructions, \
    code_generation, pretty


PASSES = collections.OrderedDict((
    ("expressions", expressions.ExpressionsEvaluator),
    ("implicits", implicits.ImplicitsProcessor),
    ("flow", flow.FlowFinder),
    ("typing", typing.Typer),
    ("specialization", specialization.Specializer),
    ("escapes", escapes.EscapesAnalyser),
    ("uses", uses.UsesChecker),
    ("destructions", destructions.Destructor),
))


util.PASSES_PRECEDENCE = {}
previous_pass_name = None
for pass_name in PASSES:
    util.PASSES_PRECEDENCE[pass_name] = previous_pass_name
    previous_pass_name = pass_name


# Get the target machine which always is the host
# TODO: Implement a way to user pass the target machine via command line
llvm.initialize_native_target()
target = llvm.Target.from_default_triple()
TARGET_MACHINE = target.create_target_machine(jit=False)

CORE_MODULE = None


def create_module(file, is_core=False):
    """
    Takes a file, returns a Module containing declarations and code objects, to be submitted for further processing.
    """
    if not os.path.isfile(file):
        msg = (None, "\n\n\tno file named '{name}' was found".format(name=file))
        hints = ["Check whether the file is in the project folder or system path."]
        raise util.Error([msg], hints=hints)

    # Parse the file and get the root node of the AST (abstract syntax tree)
    with open(file) as f:
        src = f.read() + "\n"
        state = parser.State(file, src)
    root_node = parser.parse(src, state)

    # Create the module from AST tree
    builtin_module = CORE_MODULE if not is_core else None
    module = module_.Module(file, root_node, builtin_module=builtin_module, is_core=is_core)

    return module


def process_file(input_file, last_pass=None):

    def get_module(file, is_core=False, is_main_file=False):

        def import_object(obj_module, obj_pos, obj_original_name, obj_name, obj_node):

            for obj in objects_to_import:
                if obj["module"].file == obj_module.file and obj["original_name"] == obj_original_name:
                    msg = (obj["pos"], "object named '{name}' was imported here".format(name=obj_original_name))
                    msg2 = (obj_pos, "but was imported again here")
                    raise util.Error([msg, msg2])

            objects_to_import.append({"module": obj_module, "pos": obj_pos, "original_name": obj_original_name})
            if isinstance(obj_node, (ast.Class, ast.Trait)) or \
               (isinstance(obj_node, ast.Function) and isinstance(obj_node.ret, ast.DerivedType) and obj_node.ret.name == "iterator"):
                module.types.imported_modules.setdefault(obj_module.types, []).append([obj_name, obj_original_name])
            else:
                module.symbols.imported_modules.setdefault(obj_module.symbols, []).append([obj_name, obj_original_name])

        def process_importation(node, module_path):

            def get_module_file(path):
                file = None
                include_dirs = [root_dir, util.STANDARD_LIB_DIR]
                for dir in include_dirs:
                    dir = os.path.join(dir, *path)
                    if os.path.isfile(dir + ".zz"):
                        file = dir + ".zz"
                        break
                    elif os.path.isfile(os.path.join(dir, "__init__.zz")):
                        file = os.path.join(dir, "__init__.zz")
                        break
                return file

            # Check if the file exists
            last_name = node.path.names[-1]
            module_file = get_module_file(module_path)
            if module_file is None:
                msg = (last_name.pos, "no module named '{name}' was found".format(name=last_name.name))
                hints = ["Check whether there is a typo in the name.",
                         "Check if it is in the project folder or system path."]
                raise util.Error([msg], hints=hints)

            # Create or get the imported module
            module = get_module(module_file)
            dependencies[file].add(module_file)

            # If no object is specified then import all objects from file
            if node.objects is None:

                # Get the correct name of the module
                if node.path_alias is not None:
                    module_name = node.path_alias.name
                else:
                    module_name = ".".join(module_path)

                # Append the objects as being part of this module
                for original_name, obj_node in module.symbols.current_itens.items():
                    new_name = "{module}.{name}".format(module=module_name, name=original_name)
                    import_object(module, node.path.pos, original_name, new_name, obj_node)

                # Check if there are submodules and import them too
                module_dir = os.path.dirname(module_file)
                for item in os.listdir(module_dir):
                    if (item.endswith(".zz") and item != "__init__.zz") or \
                            (os.path.isdir(os.path.join(module_dir, item)) and
                             os.path.isfile(os.path.join(module_dir, item, "__init__.zz"))):
                        sub_module = os.path.splitext(item)[0]
                        sub_path = module_path + [sub_module]
                        module_file = get_module_file(sub_path)
                        if module_file is not None:
                            sub_node = ast.Import(node.path.pos,
                                                  ast.ImportPath(node.path.pos, [ast.Name(node.path.pos, sub_module)]),
                                                  path_alias=None)
                            process_importation(sub_node, sub_path)

            # Import the selected objects from module
            if node.objects is not None:
                for obj in node.objects:

                    # Get the correct name of the object
                    if obj["alias"] is not None:
                        obj_name = obj["alias"].name
                    else:
                        obj_name = obj["name"].name

                    # Append the imported object as being part of this module
                    found = False
                    for original_name, obj_node in module.symbols.current_itens.items():
                        if obj["name"].name == original_name:
                            import_object(module, obj["name"].pos, obj["name"].name, obj_name, obj_node)
                            found = True
                            break

                    # If object not found, check if name is a submodule
                    if not found:
                        sub_path = module_path + [obj["name"].name]
                        module_file = get_module_file(sub_path)
                        if module_file is not None:
                            sub_node = ast.Import(obj["name"].pos, ast.ImportPath(obj["name"].pos, [obj["name"]]),
                                                  path_alias=obj["alias"])
                            process_importation(sub_node, sub_path)
                        else:
                            msg = (obj["name"].pos, "no object named '{name}' was found".format(name=obj["name"].name))
                            hints = ["Check whether there is a typo in the name.",
                                     "Check if it was defined in the module."]
                            raise util.Error([msg], hints=hints)

        # Create the module if it doesn't exist
        if file not in modules:

            objects_to_import = []
            root_dir = os.path.dirname(file)
            module = create_module(file, is_core=is_core)
            modules[file] = module
            dependencies[file] = set()

            # Process the imported files to get objects
            for importation_name, node in module.symbols.current_itens.items():
                if isinstance(node, ast.Import):
                    process_importation(node, [name.name for name in node.path.names])

        else:
            module = modules[file]

        # If the binary output is an executable and not a library, check if it has the function 'main'
        if is_main_file and not util.OUTPUT_IS_LIBRARY:
            main_fn = module.symbols.get("main", None)
            if main_fn is None or not isinstance(main_fn, ast.Function):
                msg = (None, "\n\n\tno function named 'main' was found")
                raise util.Error([msg])

        return module

    modules = {}
    dependencies = {}
    ordered_modules = collections.OrderedDict()

    # Create CORE module if necessary
    global CORE_MODULE
    if CORE_MODULE is None:
        core_file = os.path.join(util.CORE_DIR, "__builtins__.zz")
        CORE_MODULE = get_module(core_file, is_core=True)
        ordered_modules[CORE_MODULE.file] = modules[CORE_MODULE.file]

    # Create the main module
    module = get_module(input_file, is_main_file=True)

    # Traverse all module dependencies to create an ordered list of modules to process
    remains = set(dependencies)
    while len(remains) > 0:

        # Write out modules with no dependencies
        done = set()
        for file in remains:
            if len(dependencies[file]) == 0:
                ordered_modules[file] = modules[file]
                done.add(file)

        # Remove the processed modules from dependency lists
        remains -= {file for file in done}
        for remain_file in remains:
            for done_file in done:
                if done_file in dependencies[remain_file]:
                    dependencies[remain_file].remove(done_file)

        assert len(done) > 0, len(remains) > 0  # check that we made progress

    # Execute the passes in the AST and CFG trees of the module
    for pass_name, ProcessorClass in PASSES.items():
        for file, module in ordered_modules.items():
            processor = ProcessorClass(module)
            processor.process()
            module.processors[pass_name] = processor
        if last_pass is not None and pass_name == last_pass:
            break

    return ordered_modules


def show_pretty_ir(file, last_pass=None):
    """
    Show Ragaz high-level intermediate representation for the source code in the given file name (`file`).
    `last_pass` contains the last pass from PASSES to apply to the module before generating the IR.
    """
    modules = process_file(file, last_pass=last_pass)
    pp = pretty.Prettifier(modules[file])
    pretty_ir = pp.process()
    return pretty_ir


def find_clang():
    min_version = 11
    max_version = 15
    compatible_versions = range(min_version, max_version + 1)
    for version in compatible_versions:
        compiler = "clang-" + str(version)
        try:
            subprocess.check_call([compiler, "--version"], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
            return compiler
        except:
            pass
    raise Exception("error: no compatible clang ({versions}) was found"
                    .format(versions=", ".join([str(version) for version in compatible_versions])))


def execute_clang(cmd):
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError:
        pass


def compile(input_file, output_file, output_is_library=False, use_optimization=True, emit_llvm=False, enable_debug=False,
            show_warnings=True, colored_messages=True, automatic_casting=True, mutability_checking=False):
    """
    Compiles LLVM assembly into a binary. Takes a string file name and a string output file name. Writes LLVM assembly
    to a temporary file for the main module as well as personality, rt, and builtins modules, then calls clang on them.
    """

    # Set compiler directives
    util.OUTPUT_IS_LIBRARY = output_is_library
    util.SHOW_WARNINGS = show_warnings
    util.COLORED_MESSAGES = colored_messages
    util.AUTOMATIC_CASTING = automatic_casting
    util.MUTABILITY_CHECKING = mutability_checking

    # Process the file getting its module and its submodules and finally processing these in every compiler pass
    modules = process_file(input_file)

    # Prepare a dict to store LLVM assembly files and their content
    core_ir_file = os.path.join(util.CORE_DIR, "__builtins__.ll")
    ir_files = {core_ir_file: str(CORE_MODULE.ir)}

    # Generate a string of LLVM assembly for every imported module in input file
    for file, module in modules.items():
        code_generation.generate_module_ir(TARGET_MACHINE, module)
        module_ir_file = file.rsplit(".zz")[0] + ".ll"
        ir_files[module_ir_file] = module.ir

    # Save all LLVM assembly files
    for file, ir in ir_files.items():
        with open(file, "w") as f:
            f.write(str(ir))

    triple = TARGET_MACHINE.triple
    clang_compiler = find_clang()

    # Create the personality LLVM assembly file using clang++
    error_handle_dir = os.path.join(util.CORE_DIR, "personality")
    error_handle_cpp_file = os.path.join(error_handle_dir, "personality.c")
    error_handle_ir_file = os.path.join(error_handle_dir, "personality.ll")
    ir_files[error_handle_ir_file] = None
    cmd = [clang_compiler,
           "-target", triple,
           "-S", "-emit-llvm",
           "-o", error_handle_ir_file,
           "-O2" if use_optimization else "",
           "-g" if enable_debug else "",
           "-Wno-override-module",
           error_handle_cpp_file]
    execute_clang(cmd)

    # Complete the binary file's name if necessary
    if output_file is None:
        output_file = input_file.rsplit(".zz")[0]
    output_file = os.path.abspath(output_file)
    _, output_extension = os.path.splitext(output_file)
    if output_extension == "":
        if util.OUTPUT_IS_LIBRARY:
            if "windows" in triple:
                output_extension = ".dll"
            else:
                output_extension = ".so"
        else:
            if "windows" in triple:
                output_extension = ".exe"
            else:
                output_extension = ".a"
        output_file += output_extension

    # Build the binary using all LLVM assembly files generated
    cmd = [clang_compiler,
           "-target", triple,
           "-m64" if triple.split("-")[0] == "x86_64" else "-m32",
           "-o", output_file,
           "-lm",  # Mathematics library
           "-O2" if use_optimization else "",
           "-g" if enable_debug else "",
           "-fPIC" if util.OUTPUT_IS_LIBRARY else "",
           "-shared" if util.OUTPUT_IS_LIBRARY else "",
           "-Wno-override-module"]
    if "windows-msvc" in triple:
        library_unwind_file = os.path.join(error_handle_dir, "libunwind.dll.a")
        cmd.append(library_unwind_file)
    cmd += ir_files.keys()
    execute_clang(cmd)

    # Clean LLVM assembly files after binary file is created
    if not emit_llvm:
        for file in ir_files.keys():
            os.unlink(file)

    main_ir_file = input_file.rsplit(".zz")[0] + ".ll"
    return ir_files[main_ir_file]
