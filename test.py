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
        print(self.options)
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
    tests = []
    test_dir = os.path.join(DIR, "tests", sub_dir)
    for file in os.listdir(test_dir):
        file = os.path.join(test_dir, file)
        if file.endswith(".zz"):
            tests.append(RagazTest(file))
    return tests


def get_all_tests():
    tests = []
    tests.extend(get_tests_from_dir("ragaz"))
    tests.extend(get_tests_from_dir("standard_lib"))
    return tests


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
