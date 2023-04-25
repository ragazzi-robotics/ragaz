import os

BASE = os.path.dirname(os.path.dirname(__file__))
CORE_DIR = os.path.join(BASE, "ragaz", "core")
STANDARD_LIB_DIR = os.path.join(BASE, "standard_lib")

# Compiler directives
OUTPUT_IS_LIBRARY = False
SHOW_WARNINGS = True
COLORED_MESSAGES = True
AUTOMATIC_CASTING = True
MUTABILITY_CHECKING = False

PASSES_PRECEDENCE = {}


class Repr(object):
    """
    Helper class to provide a nice __repr__ for other classes
    """
    unreachable = False

    def __repr__(self):
        ignore = {"pos"}
        contents = sorted(self.__dict__.items())
        show = ("{attribute}={content!r}".format(attribute=attribute, content=content)
                for (attribute, content) in contents if attribute not in ignore)
        return "<{cls}({attributes})>".format(cls=self.__class__.__name__, attributes=", ".join(show))


def check_previous_pass(module, fn, curr_pass_name):
    previous_pass_name = PASSES_PRECEDENCE[curr_pass_name]
    if previous_pass_name is not None and previous_pass_name not in fn.passes:
        module.processors[previous_pass_name].visit_function(fn)


class ScopesDict(object):

    def __init__(self, parent=None):
        self.parent = parent
        self.current = {}

    def __repr__(self):
        return "<ScopesDict({parent}, {current!r})>".format(parent=id(self.parent), current=self.current)

    def find_dict(self, key, error_if_not_found=False):
        if self.parent is not None and key in self.parent:
            return self.parent
        else:
            return self.current

    def __contains__(self, key):
        return key in self.current or (self.parent is not None and key in self.parent)

    def __getitem__(self, key):
        if key in self.current:
            return self.current[key]
        elif self.parent is not None:
            return self.parent[key]
        else:
            assert False, "Item not found: {item}".format(item=key)

    def __setitem__(self, key, value):
        self.current[key] = value

    def __delitem__(self, key):
        if key in self.current:
            del self.current[key]
        elif self.parent is not None:
            del self.parent[key]
        else:
            assert False, "Item not found: {item}".format(item=key)

    def __iter__(self):
        all = self.current
        if self.parent is not None:
            all.update(self.parent.current)
        return iter(all)

    def keys(self):
        all = list(self.current.keys())
        if self.parent is not None:
            all.extend(list(self.parent.current.keys()))
        return all

    def values(self):
        all = list(self.current.values())
        if self.parent is not None:
            all.extend(list(self.parent.current.values()))
        return all

    def get(self, key, default=None):
        return self[key] if key in self else default


def show_message(msg_type, messages, hints):
    """
    Helper function to print useful error messages.

    Tries to mangle location information and message into a layout that's easy to read and provides good data about the
    underlying error message.
    """
    def format_text(msg, format):
        if COLORED_MESSAGES:
            return format + msg + "\x1b[0m"
        else:
            return msg

    BOLD = "\x1b[0;0;1m"
    RED_BOLD = "\x1b[1;5;31m"
    BLUE_UNDERLINE = "\x1b[4;6;34m"
    BLUE = "\x1b[4;0;34m"
    BLUE_BOLD = "\x1b[1;5;34m"
    YELLOW_BOLD = "\x1b[1;5;33m"

    if msg_type == "WARNING":
        msg_color = YELLOW_BOLD
    elif msg_type == "ERROR":
        msg_color = RED_BOLD
    else:
        msg_color = BLUE_BOLD

    max_indent = 4
    for file, pos, msg in messages:
        if pos is not None:
            row = pos[0][0]
            curr_indent = len(str(row)) + 1
            if curr_indent > max_indent:
                max_indent = curr_indent
    indent = " " * max_indent

    text = "@" + format_text("\n{title}\n{underline}".format(title=msg_type,
                                                               underline="=" * len(msg_type)), msg_color)

    last_file = None
    for file, pos, msg in messages:
        if pos is not None:
            row, col, src = pos[0][0], pos[0][1], pos[2]
        else:
            src = None

        if file is not None:
            if last_file != file:
                path = "\n\n" + indent + "In {file}:".format(file=format_text(file, BLUE_UNDERLINE))
                if src is None:
                    text += path + " "
                else:
                    text += path + "\n"
        last_file = file

        msg = format_text(msg, msg_color)
        if src is None:
            text += msg + "\n"
        else:
            text += "\n" + indent + "|"

            # Source line where the error/warning was raised
            fmt = "{0: >" + str(max_indent - 1) + "} "
            line = fmt.format(row + 1)
            text += "\n" + format_text(line, BOLD) + "| " + src.replace("\t", indent).rstrip()

            num_spaces = (col + (3 * min(col, src.count("\t"))))
            spaces = " " * num_spaces

            # Pointer bellow source line indicating where is the error/warning
            text += "\n" + indent + "| " + spaces + format_text("^", msg_color)

            # The message itself...
            text += "\n" + indent + "| " + spaces + format_text(msg, msg_color)

    if hints is not None:
        text += "\n\n" + indent + format_text("Hint:\n", BLUE_BOLD)
        text += format_text("\n".join([indent + "- " + hint for hint in hints]), BLUE)

    text += "\n@"

    return text


def warn(msgs, hints=None):
    """
    Warning function used for print warnings from the compiler
    """
    if SHOW_WARNINGS:
        messages = []
        for message in msgs:
            pos = message[0]
            msg = message[1]
            if pos is not None and len(pos) == 4:
                file = os.path.basename(pos[3])
            else:
                file = None
            messages.append((file, pos, msg))
        print(show_message("WARNING", messages, hints=hints))


class Error(Exception):
    """
    Error class used for throwing user errors from the compiler
    """

    def __init__(self, pos_and_messages, hints=None):
        messages = []
        for message in pos_and_messages:
            pos = message[0]
            msg = message[1]
            if pos is not None and len(pos) == 4:
                file = os.path.basename(pos[3])
            else:
                file = None
            messages.append((file, pos, msg))

        self.message = show_message("ERROR", messages, hints)
        Exception.__init__(self, self.message)

    def show(self):
        return self.message
