#!/usr/bin/env python

from __future__ import print_function
import optparse
import sys
import os
from ragaz import parser, util, compiler


if __name__ == "__main__":

    def print_tokens(file, options):
        """
        Print the list of tokens and location info
        """
        with open(file) as f:
            src = f.read() + "\n"
            state = parser.State(file, src)
        tokens = parser.lex(src, state)
        for token in tokens:
            print(token.name, token.value, (token.source_pos.lineno, token.source_pos.colno))

    def print_ast(file, options):
        """
        Print the AST tree resulting from parsing the source
        """
        with open(file) as f:
            src = f.read() + "\n"
            state = parser.State(file, src)
        print(parser.parse(src, state))

    def print_cfg(file, options):
        """
        Print CFG flow after processing the pass specified by --last
        """
        for ir in compiler.show_pretty_ir(file, options["last"]):
            print(ir)

    def print_generated_code(input_file, options):
        """
        Print LLVM assembly emitted by the code generation process
        """
        ir = compile_file(input_file, options)
        print(ir)

    def compile_file(input_file, options):
        """
        Compile the given program to a binary of the same name
        """
        ir = compiler.compile(input_file, options["outfile"],
                              output_is_library=options["output_is_library"],
                              emit_llvm=options["emit_llvm"],
                              show_warnings=not options["no_warning_messages"],
                              colored_messages=not options["no_colored_messages"],
                              automatic_casting=not options["no_auto_cast"],
                              mutability_checking=options["mut_check"])
        return ir

    # Command line allowed arguments
    optparser = optparse.OptionParser(usage="usage: %prog command input_file [options]")
    optparser.add_option("--last", help="execute analysis until the pass", default="destruct")
    optparser.add_option("-o", "--outfile", help="binary output file", dest="outfile")
    optparser.add_option("--test", help="test without generate output", action="store_true")
    optparser.add_option("--traceback", help="show full traceback", action="store_true")
    optparser.add_option("--output-is-library", help="output is library", action="store_true")
    optparser.add_option("--emit-llvm", help="generate LLVM assembly", action="store_true")
    optparser.add_option("--no-warning-messages", help="disable warning messages", action="store_true")
    optparser.add_option("--no-colored-messages", help="disable colored warning/error messages", action="store_true")
    optparser.add_option("--no-auto-cast", help="disable automatic types casting", action="store_true")
    optparser.add_option("--mut-check", help="check variables mutability", action="store_true")
    options, args = optparser.parse_args()
    options = vars(options)

    commands = {
        "tokens": print_tokens,
        "ast": print_ast,
        "cfg": print_cfg,
        "generated_code": print_generated_code,
        "compile": compile_file,
    }

    # If no arguments were passed then print help message to the user
    if len(args) == 0:
        print("The Ragaz compiler. A command takes a single file as an argument.")
        print("\nCommands:\n")
        for cmd, fn in sorted(commands.items()):
            print("{cmd}: {help}".format(cmd=cmd, help=fn.__doc__))
        print("")
        optparser.print_help()
        sys.exit(1)

    # Get the command which always must be the first argument
    cmd = args[0]
    if cmd not in commands:
        print("error: no command found: {cmd!r}".format(cmd=cmd))
        sys.exit(1)

    # Get the input file which always must be the second argument
    if len(args) < 2:
        print("error: no input file")
        sys.exit(1)
    else:
        input_file = os.path.abspath(args[1])

    # Execute the related function to perform the command, passing the input file and the other command line options
    # to it
    fn = commands[cmd]
    try:
        fn(input_file, options)
    except util.Error as e:
        if options["traceback"]:
            raise
        sys.stderr.write(e.show())
