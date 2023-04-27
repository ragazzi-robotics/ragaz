from __future__ import print_function
import json
import os
import subprocess
import sys
import unittest
from ragaz import util
from ragaz.compiler import show_pretty_ir, compile

DIR = os.path.dirname(__file__)


class RagazTest(unittest.TestCase):

    def __init__(self, file):
        unittest.TestCase.__init__(self)
        self.file = file
        self.base = self.file.rsplit(".zz", 1)[0]
        self.binary_file = self.base + ".test"
        self.options = self.get_options()

    def get_options(self):
        with open(self.file) as f:
            h = f.readline()
            if h.startswith("# test: "):
                return json.loads(h[8:])
            else:
                return {}

    def compile(self):
        if self.options.get("type", "test") == "show":
            return [0, "\n".join(show_pretty_ir(self.file)) + "\n", ""]

        output_is_library = "output_is_library" in self.options
        show_warnings = "show_warnings" in self.options
        automatic_casting = "no_auto_cast" not in self.options
        mutability_checking = "mut_check" in self.options
        if os.path.exists(self.binary_file):
            os.unlink(self.binary_file)
        try:
            compile(self.file, self.binary_file,
                    output_is_library=output_is_library,
                    emit_llvm=True,
                    enable_debug=True,
                    use_optimization=False,
                    show_warnings=show_warnings,
                    colored_messages=False,
                    automatic_casting=automatic_casting,
                    mutability_checking=mutability_checking)
            return [0, "", ""]
        except util.Error as e:
            return [0, "", e.show()]
        except:
            return [0, "", "{type}: {msg}".format(type=sys.exc_info()[0].__name__, msg=sys.exc_info()[1])]

    def runTest(self):

        res = self.compile()
        if any(res) and sys.version_info[0] > 2:
            for i, s in enumerate(res[1:]):
                res[i + 1] = s

        if not any(res):
            cmd = [self.binary_file] + self.options.get("args", [])
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, err = proc.communicate()
            out = out.decode("utf-8").replace("\r\n", "\n")  # This fix output from tests on Windows
            err = err.decode("utf-8")
            res = [proc.returncode, out, err]

        # Fill the `expected` result according to previous file in directory
        # A test have either an output file (when it is expected a successful compilation) or an error file (when it is
        # expected a given compilation error)
        expected = [self.options.get("ret", 0), "", ""]
        for i, ext in enumerate((".out", ".err")):
            if os.path.exists(self.base + ext):
                with open(self.base + ext, "r") as f:
                    expected[i + 1] = f.read()

        if self is None:
            return res == expected
        elif len(expected[1]) > 0:
            # Compare output messages
            if expected[1] != res[1]:
                print(self.base, "expected: [", expected[1], "] returned: [", res[1], "]")
            self.assertEqual(expected[1], res[1])
        elif len(expected[2]) > 0:
            # Compare error messages
            if expected[2] != res[2]:
                print(self.base, "expected: [", expected[2], "] returned: [", res[2], "]")
            self.assertEqual(expected[2], res[2])


def get_tests_from_dir(sub_dir):
    files = []
    test_dir = os.path.join(DIR, "tests", sub_dir)
    for file in os.listdir(test_dir):
        file = os.path.join(test_dir, file)
        if file.endswith(".zz"):
            files.append(file)
    return files


def get_all_tests():
    files = []
    files.extend(get_tests_from_dir("ragaz"))
    files.extend(get_tests_from_dir("standard_lib"))
    
    
    files = [#'/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/ref-mutable-not-allowed.zz', 
             '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/bitwise-binop-mismatch-types.zz', 
             '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/ref-passed-as-owner-arg.zz', 
             '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/contains.zz', 
             '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/type-checking.zz', 
             '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/method-not-found.zz', 
             '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/print.zz', 
             '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/bool-mismatch-types.zz', 
             '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/data-pointer-corrupt-top-size.zz', 
             '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/ref-immutable.zz', 
             '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/bitwise.zz', 
             '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/bool-comparison.zz', 
             '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/array.zz', 
             '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/data-pointer-realloc-wrong-object.zz', 
             '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/main-args.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/owner-copy-instead-move-to-call.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/owner-reassign-lost-reference.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/call-wrong-callable.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/imported-object-not-found.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/var-defined-inner-scope.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/data-pointer-realloc-wrong-elements.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/iterator-return.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/call.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/exception-inline-catch.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/function-wrong-default-arg.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/set.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/var-mismatch-type.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/none.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/attribute-not-found.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/arithmetics-binop-mismatch-types.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/call-mismatch-params.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/function-not-found.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/array-wrong-elements.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/trait-duplicated-method.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/iterator-class.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/parse-unexpected-indent.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/owner-after-move-symbol-to-tuple.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/tuple-wrong-num-elements.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/generics.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/function-no-return.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/if.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/parse-mix-tabs-and-spaces.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/ternary.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/abs.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/value-not-allowed-type-class.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/while.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/main-type-return.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/return-multi-values.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/owner-after-move-symbol-to-function.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/tuple-wrong-idx.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/method-type.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/list-wrong-num-elements.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/globals.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/element-no-set-item.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/list.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/dict.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/memory.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/method-no-arg.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/ref-mutable.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/var-half-defined.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/trait-no-method.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/tuple.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/method-arg-self-missing.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/cast-manual.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/parse-mismatch-indent.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/main-type-arg-0.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/char.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/owner-after-move-and-return.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/bitwise-unop-mismatch-types.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/init-return-type.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/return-mismatch-type.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/class.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/var-definition-missing-type.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/tuple-assign-wrong-value.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/method-named-args.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/trait.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/bool-logical.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/iterator-generator.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/method-arg-missing-type.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/parse-invalid-syntax-incomplete.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/tuple-assign-wrong-values.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/element-wrong-idx.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/call-missing-param.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/type-alias-extra-item.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/main-no-existent.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/list-wrong-default-value.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/contains-no-method.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/data-pointer-movememory-wrong-object.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/ref-return.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/element-no-get-item.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/method-arg-self-misname.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/file.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/string.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/exception-unhandled.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/loop-jumpers.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/arithmetics-negate-unsigned.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/owner-after-partial-move-attribute-to-function.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/method-arg-positioned-after-named.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/owner-mutable.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/imported-module-not-found.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/generics-type-var-duplicated.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/return-check-type-void.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/return-force-void.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/type-alias.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/collection-mismatch-types.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/owner-reassign.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/bin.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/ternary-mismatch-type.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/data-pointer-offset-wrong-type.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/decorator-not-found.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/var-shadowing.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/imported-object-duplicated.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/parse-invalid-syntax-inexistent-token.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/oct.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/list-empty.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/call-no-return.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/parse-invalid-syntax-existent-token.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/cast-manual-mismatch-types.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/function-type.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/type-not-found.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/mix-types.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/var-not-found.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/method-select-fail.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/class-non-initialized-attributes.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/owner-copy-instead-move-to-symbol.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/yield-type.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/ref-deref.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/owner-after-move-attribute-to-function.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/arithmetics.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/ref-deref-non-pointer.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/import.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/pretty.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/ref-out-of-scope.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/class-no-init.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/value-not-allowed-type-basic.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/var-multi-assignments.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/hex.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/owner-return.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/data-pointer-offset-wrong-idx.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/list-mismatch-types.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/arithmetics-unop-mismatch-type.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/function-type-mismatch-types.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/bool-precedence.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/data-pointer-copymemory-wrong-object.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/for.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/exception-catch.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/ragaz/method-arg-self-explicit-type.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/standard_lib/random_.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/standard_lib/sys.output.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/standard_lib/os-environ.zz', '/home/travis/build/ragazzi-robotics/ragaz/tests/standard_lib/time_.zz']    
    
    
    
    return [RagazTest(file) for file in files]


def suite():
    suite = unittest.TestSuite()
    suite.addTests(get_all_tests())
    return suite


def execute_valgrind(test):
    """
    The Valgrind tool suite provides a number of debugging and profiling tools that help you make your programs
    faster and more correct. The most popular of these tools is called Memcheck. It can detect many memory-related
    errors that are common in C and C++ programs and that can lead to crashes and unpredictable behaviour.
    """

    args = test.options.get("args", [])
    cmd = ["valgrind", "--leak-check=full", test.binary_file] + args
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    _, err = proc.communicate()
    err = err.decode("utf-8")

    blocks, curr_block = [], []
    for ln in err.splitlines():
        if ln.startswith("=="):

            # Remove the process ID which is in the format '==99999=='
            ln = ln.split("== ")[1]

            # Is a blank line? Then the leak is finished
            if len(ln.strip()) == 0:
                if len(curr_block) > 0:
                    blocks.append(curr_block)
                    curr_block = []

            # Else, just put another line to the leak
            else:
                curr_block.append(ln)

    # Count the valid blocks as errors
    errors = 0
    ignore = ["HEAP SUMMARY:", "LEAK SUMMARY:", "WARNING:", "Memcheck", "All heap blocks", "For counts"]
    for block in blocks:
        if not any(flag for flag in ignore if block[0].startswith(flag)):
            errors += 1

    return errors


def check_leaks():
    tests = get_all_tests()
    max_col = max([len(test.binary_file) for test in tests]) + 1

    # Traverse all binaries generated by the tests looking for memory leaks
    for test in tests:

        # Compile again the test file if necessary
        compiled = os.path.exists(test.binary_file)
        if not compiled or os.stat(test.file).st_mtime >= os.stat(test.binary_file).st_mtime:
            res = test.compile()
            err = res[2] is not None
            if err:
                continue

        # Look for memory leaks
        print("Checking {binary_file}...".format(binary_file=test.binary_file), end=" ")
        count = execute_valgrind(test)
        print(" " * (max_col - len(test.binary_file)), "{count:3}".format(count=count))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--leaks-check":
        check_leaks()
    else:
        unittest.main(defaultTest="suite")
