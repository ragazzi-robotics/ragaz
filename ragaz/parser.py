import rply
from ragaz import ast_ as ast, util


KEYWORDS = [
    "AND", "AS", "BREAK", "CALLABLE", "CLASS", "CONTINUE", "DEF", "DEL", "ELIF", "ELSE", "EXCEPT",
    "FOR", "FROM", "IF", "IMPORT", "IN", "IS", "ISINSTANCE", "NOT", "OR", "PASS",
    "RAISE", "RETURN", "SIZEOF", "TRAIT", "TRANSMUTE", "TRY", "VAR", "WHILE", "YIELD",
]


OPERATORS = [
    ("DOT", "\."),
    ("L_PAREN", "\("),
    ("R_PAREN", "\)"),
    ("ARROW", "->"),
    ("INPLACE_ADD", "\+="),
    ("INPLACE_SUB", "-="),
    ("INPLACE_MUL", "\*="),
    ("INPLACE_DIV", "/="),
    ("INPLACE_MOD", "%="),
    ("INPLACE_FLOOR_DIV", "//="),
    ("INPLACE_POW", "\*\*="),
    ("INPLACE_SHIFT_LEFT", "<<="),
    ("INPLACE_SHIFT_RIGHT", ">>="),
    ("INPLACE_BW_AND", "&="),
    ("INPLACE_BW_OR", "\|="),
    ("INPLACE_BW_XOR", "\^="),
    ("POW", "\*\*"),
    ("PLUS", "\+"),
    ("MINUS", "-"),
    ("MUL", "\*"),
    ("FLOOR_DIV", "//"),
    ("DIV", "/"),
    ("MOD", "%"),
    ("EQUAL", "=="),
    ("NOT_EQUAL", "!="),
    ("LESS_EQUAL", "<="),
    ("LESS_THAN", "<"),
    ("GREATER_EQUAL", ">="),
    ("GREATER_THAN", ">"),
    ("L_BRACKET", "\["),
    ("R_BRACKET", "\]"),
    ("L_BRACE", "{"),
    ("R_BRACE", "}"),
    ("AMP", "&"),
    ("PIPE", "\|"),
    ("CARET", "\^"),
    ("TILDE", "~"),
    ("ASSIGN", "="),
    ("COMMA", ","),
    ("COLON", ":"),
    ("AT", "\@"),
    ("MULTILINE_STRING", '"""(.*?|\n)*?"""'),
    ("STRING", '"(.*?)"'),
    ("BOOL", "True|False"),
    ("NONE", "None"),
    ("IDENTIFIER", "[a-zA-Z_][a-zA-Z0-9_]*"),
    ("HEX", "0x[a-fA-F0-9]+"),
    ("OCT", "0o[0-7]+"),
    ("BIN", "0b[0-1]+"),
    ("FLOAT", "[-+?[0-9]+\.[0-9]+"),
    ("INT", "[-+[0-9]+"),
    ("CHAR", "'.'|'\\[n|r|t|b|f]'"),
    ("NEW_LINE", "\n"),
    ("COMMENT", "#(.*)"),
    ("SPACES", " +"),
    ("TABS", "\t+"),
]


MAGIC_METHODS = {
    "bin": "__bin__",
    "bool": "__bool__",
    "copy": "__copy__",
    "hex": "__hex__",
    "iter": "__iter__",
    "len": "__len__",
    "next": "__next__",
    "oct": "__oct__",
    "repr": "__repr__",
}


def lexer():
    lg = rply.LexerGenerator()
    for token, value in OPERATORS:
        lg.add(token, value)
    return lg.build()


LEXER = lexer()


def lex(src, state):
    """
    Takes a string containing source code and returns a generator over
    tokens, represented by a three-element tuple:

    - Token type (from the list in lexer(), above)
    - The literal token contents
    - Position, as a tuple of line and column (both 1-based)

    This is mostly a wrapper around the rply lexer, but it reprocesses
    TABS tokens (which should only appear at the start of a line) into
    INDENT and DEDENT tokens, which only appear if the indentation
    level increases or decreases.

    Comment tokens do not appear in the output generator.
    """
    indent_char = None
    indent_len = None

    level = 0
    hold = []
    tokens = []
    must_indent = False
    last_valid_token = None
    for token in LEXER.lex(src):

        # Skip whitespaces and comments
        if token.name == "COMMENT":
            continue
        elif token.name == "NEW_LINE":
            hold = [token]
            token.last_valid_token = last_valid_token
            continue
        elif token.name == "SPACES" or token.name == "TABS":
            if len(hold) > 0:
                if indent_char is None:
                    indent_char = token.name
                    indent_len = len(token.value)
                elif token.name != indent_char:
                    msg = (state.pos(token), "mixing tabs and spaces is not allowed for indentation")
                    raise util.Error([msg])
                hold.append(token)
            continue
        last_valid_token = token

        if token.name == "COLON":
            must_indent = True

        # Handle indentation
        if len(hold) > 0:
            tokens.append(hold[0])  # Append NEW_LINE to tokens

            # Get indentation level
            if len(hold) > 1:
                tabs = len(hold[1].value) // indent_len
                remain = len(hold[1].value) % indent_len
                if remain != 0:
                    msg = (state.pos(token), "indentation does not match any outer level")
                    raise util.Error([msg])
            else:
                tabs = 0

            # Get position from last tab
            pos = hold[1 if len(hold) > 1 else 0].source_pos

            # Append INDENT or DEDENT according to current level
            for i in range(abs(tabs - level)):
                if tabs > level:
                    if must_indent:
                        typ = "INDENT"
                        must_indent = False
                    else:
                        last_token = tokens[-2]
                        msg = (state.pos(last_token), "there is no colon after this")
                        msg2 = (state.pos(token), "but the indentation is incremented")
                        hints = ["Have you forgotten to write the colon?"]
                        raise util.Error([msg, msg2], hints=hints)
                else:
                    typ = "DEDENT"
                tokens.append(rply.Token(typ, "", pos))
                level = tabs
            hold = []

        # Make uppercase all keywords
        if token.name == "IDENTIFIER" and token.value.upper() in KEYWORDS:
            token.name = token.value.upper()

        tokens.append(token)

    for token in hold:
        tokens.append(token)

    while level > 0:
        tokens.append(rply.Token("DEDENT", "", token.source_pos))
        level -= 1

    return iter(tokens)


# Concatenate the final list of tokens which include keywords, operators, and others
tokens = list(KEYWORDS)
tokens.extend(["DEDENT", "INDENT"])
tokens.extend([token for token, value in OPERATORS
               if token not in ["COMMENT", "TABS", "SPACES"]])


pg = rply.ParserGenerator(tokens,
                          precedence=[
                              ("left", ["COMMA"]),
                              ("left", ["IF"]),
                              ("left", ["OR"]),
                              ("left", ["AND"]),
                              ("right", ["NOT"]),
                              ("nonassoc", ["LESS_THAN", "LESS_EQUAL", "GREATER_THAN", "GREATER_EQUAL",
                                            "NOT_EQUAL", "EQUAL", "IS", "IN"]),
                              ("left", ["PIPE"]),
                              ("left", ["CARET"]),
                              ("left", ["AMP"]),
                              ("left", ["PLUS", "MINUS"]),
                              ("left", ["MUL", "DIV", "FLOOR_DIV", "MOD"]),
                              ("left", ["TILDE"]),
                              ("left", ["POW"]),
                              ("left", ["L_BRACKET", "R_BRACKET"]),
                              ("left", ["L_PAREN", "R_PAREN"]),
                              ("left", ["AS"]),
                              ("left", ["DOT"]),
    ]
)


def unary_op(state, cls, p):
    pos, value = state.pos(p[0]), p[1]
    res = cls(pos, value)
    return res


def binary_op(state, cls, p):
    pos, left, right = state.pos(p[1]), p[0], p[2]
    res = cls(pos, left, right)
    return res


def check_num_arguments(pos, num_formals, num_actuals):
    if num_formals != num_actuals:
        msg = (pos, "number of arguments must be {num_formals} ({num_actuals} not allowed)"
               .format(num_formals=num_formals, num_actuals=num_actuals))
        raise util.Error([msg])


@pg.production("module : module_elements")
def module(state, p):
    suite = p[0]
    res = ast.File(suite)
    return res


@pg.production("module : NEW_LINE module")
def module(state, p):
    return p[1]


@pg.production("module_elements : module_elements module_element")
def module_elements(state, p):
    p[0].append(p[1])
    return p[0]


@pg.production("module_elements : ")
def module_elements(state, p):
    return []


@pg.production("module_element : multiline_string NEW_LINE")
def module_element(state, p):
    return p[0]


@pg.production("module_element : set_type_aliases")
def module_element(state, p):
    return p[0]


@pg.production("module_element : global_variables_declaration")
def module_element(state, p):
    return p[0]


@pg.production("module_element : function_declaration")
def module_element(state, p):
    return p[0]


@pg.production("module_element : function")
def module_element(state, p):
    return p[0]


@pg.production("module_element : class")
def module_element(state, p):
    return p[0]


@pg.production("module_element : trait")
def module_element(state, p):
    return p[0]


@pg.production("module_element : IMPORT import_path NEW_LINE")
def module_element(state, p):
    pos, path = state.pos(p[0]), p[1]
    res = ast.Import(pos, path)
    return res


@pg.production("module_element : IMPORT import_path AS identifier NEW_LINE")
def module_element(state, p):
    pos, path, path_alias = state.pos(p[0]), p[1], p[3]
    res = ast.Import(pos, path, path_alias=path_alias)
    return res


@pg.production("module_element : FROM import_path IMPORT import_objects NEW_LINE")
def module_element(state, p):
    pos, path, objects = state.pos(p[0]), p[1], p[3]
    res = ast.Import(pos, path, objects=objects)
    return res


@pg.production("import_objects : import_objects COMMA import_object")
def import_names(state, p):
    p[0].append(p[2])
    return p[0]


@pg.production("import_objects : import_object")
def import_names(state, p):
    return [p[0]]


@pg.production("import_object : identifier AS identifier")
def import_name(state, p):
    return {"name": p[0], "alias": p[2]}


@pg.production("import_object : identifier")
def import_name(state, p):
    return {"name": p[0], "alias": None}


@pg.production("import_path : import_path DOT identifier")
def import_path(state, p):
    p[0].names.append(p[2])
    return p[0]


@pg.production("import_path : identifier")
def import_path(state, p):
    return ast.ImportPath(p[0].pos, [p[0]])


@pg.production("global_variables_declaration : VAR variables_list ASSIGN literals_list NEW_LINE")
def global_variables_declaration(state, p):
    pos, variables, values = p[1].pos, p[1], p[3]
    res = ast.VariableDeclaration(pos, variables, ast.Assign(pos, variables, values))
    return res


@pg.production("literals_list : literals")
def literals_list(state, p):
    pos, elements = p[0][0].pos, p[0]
    if len(elements) == 1:
        res = elements[0]
    else:
        res = ast.Tuple(pos, elements)
    return res


@pg.production("set_type_aliases : identifiers ASSIGN types NEW_LINE")
def set_type_aliases(state, p):
    pos, aliases, types = p[0][0].pos, p[0], p[2]
    res = ast.SetTypeAliases(pos, aliases, types)
    return res


@pg.production("trait : TRAIT identifier LESS_THAN identifiers GREATER_THAN COLON NEW_LINE INDENT function_declarations DEDENT")
def trait(state, p):
    type_vars = {identifier.name: ast.TypeVar(identifier.pos, identifier.name) for identifier in p[3]}
    pos, decor, identifier, type_vars, methods = state.pos(p[0]), set(), p[1], type_vars, p[8]
    res = ast.Trait(pos, decor, identifier.name, type_vars, methods)
    return res


@pg.production("trait : TRAIT identifier COLON NEW_LINE INDENT function_declarations DEDENT")
def trait(state, p):
    pos, decor, identifier, type_vars, methods = state.pos(p[0]), set(), p[1], {}, p[5]
    res = ast.Trait(pos, decor, identifier.name, type_vars, methods)
    return res


@pg.production("function_declarations : function_declarations function_declaration")
def function_declarations(state, p):
    p[0].append(p[1])
    return p[0]


@pg.production("function_declarations : ")
def function_declarations(state, p):
    return []


@pg.production("function_declaration : function_signature NEW_LINE")
def function_declaration(state, p):
    return p[0]


@pg.production("function : function_signature COLON suite")
def function(state, p):
    p[0].suite = p[2]
    return p[0]


@pg.production("function_signature : decorators DEF identifier LESS_THAN identifiers GREATER_THAN L_PAREN formals R_PAREN return_type")
def function_signature(state, p):
    type_vars = {identifier.name: ast.TypeVar(identifier.pos, identifier.name) for identifier in p[4]}
    pos, decorators, identifier, type_vars, args, ret = state.pos(p[6]), p[0], p[2], type_vars, p[7], p[9]
    res = ast.Function(pos, decorators, identifier.name, type_vars, args, ret)
    return res


@pg.production("function_signature : decorators DEF identifier L_PAREN formals R_PAREN return_type")
def function_signature(state, p):
    pos, decorators, identifier, type_vars, args, ret = state.pos(p[3]), p[0], p[2], {}, p[4], p[6]
    res = ast.Function(pos, decorators, identifier.name, type_vars, args, ret)
    return res


@pg.production("decorators : decorators decorator")
def decorators(state, p):
    p[0].append(p[1])
    return p[0]


@pg.production("decorators : ")
def decorators(state, p):
    return []


@pg.production("decorator : AT identifier NEW_LINE")
def decorator(state, p):
    return p[1]


@pg.production("formals : formals COMMA formal")
def formals(state, p):
    p[0].append(p[2])
    return p[0]


@pg.production("formals : formal")
def formals(state, p):
    return [p[0]]


@pg.production("formals : ")
def formals(state, p):
    return []


@pg.production("formal : identifier")
def formal(state, p):
    pos, identifier = p[0].pos, p[0]
    res = ast.Argument(pos, identifier.name)
    return res


@pg.production("formal : identifier COLON type")
def formal(state, p):
    pos, identifier, typ = p[0].pos, p[0], p[2]
    res = ast.Argument(pos, identifier.name, typ=typ)
    return res


@pg.production("formal : identifier COLON type ASSIGN expression")
def formal(state, p):
    pos, identifier, typ, default_value = p[0].pos, p[0], p[2], p[4]
    res = ast.Argument(pos, identifier.name, typ=typ, default_value=default_value)
    return res


@pg.production("formal : MUL identifier")
def formal(state, p):
    pos, name, typ = state.pos(p[0]), p[1].name, ast.VariadicArgs(state.pos(p[0]))
    res = ast.Argument(pos, name, typ=typ)
    return res


@pg.production("return_type : ")
def return_type(state, p):
    return


@pg.production("return_type : ARROW type")
def return_type(state, p):
    return p[1]


@pg.production("suite : NEW_LINE INDENT statements DEDENT")
def suite(state, p):
    return p[2]


def process_class_elements(elements):
    attributes = []
    methods = []
    for element in elements:
        if isinstance(element, tuple):
            attributes.append(element)
        elif isinstance(element, ast.Function):
            methods.append(element)
        elif isinstance(element, ast.Pass):
            break
    return attributes, methods


@pg.production("class : CLASS identifier LESS_THAN identifiers GREATER_THAN COLON NEW_LINE INDENT class_elements DEDENT")
def class_(state, p):
    type_vars = {identifier.name: ast.TypeVar(identifier.pos, identifier.name) for identifier in p[3]}
    pos, decor, identifier, type_vars, elements = state.pos(p[0]), set(), p[1], type_vars, p[8]
    attributes, methods = process_class_elements(elements)
    res = ast.Class(pos, decor, identifier.name, type_vars, attributes, methods)
    return res


@pg.production("class : CLASS identifier COLON NEW_LINE INDENT class_elements DEDENT")
def class_(state, p):
    pos, decor, identifier, type_vars, elements = state.pos(p[0]), set(), p[1], {}, p[5]
    attributes, methods = process_class_elements(elements)
    res = ast.Class(pos, decor, identifier.name, type_vars, attributes, methods)
    return res


@pg.production("class_elements : class_elements class_element")
def class_elements(state, p):
    p[0].append(p[1])
    return p[0]


@pg.production("class_elements : ")
def class_elements(state, p):
    return []


@pg.production("class_element : attribute_declaration")
def class_element(state, p):
    return p[0]


@pg.production("class_element : function")
def class_element(state, p):
    return p[0]


@pg.production("class_element : PASS NEW_LINE")
def class_element(state, p):
    return p[0]


@pg.production("class_element : multiline_string NEW_LINE")
def class_element(state, p):
    return p[0]


@pg.production("attribute_declaration : identifier COLON type NEW_LINE")
def attribute_declaration(state, p):
    return p[2], p[0]


@pg.production("statements : statements statement")
def statements(state, p):
    p[0].statements.append(p[1])
    return p[0]


@pg.production("statements : ")
def statements(state, p):
    return ast.Suite(None, [])


@pg.production("statement : TRY COLON suite EXCEPT type COLON suite")
def statement(state, p):
    pos, type, suite = state.pos(p[3]), p[4], p[6]
    handler = ast.Except(pos, type, suite)
    pos, suite = state.pos(p[0]), p[2]
    res = ast.TryBlock(pos, suite, handler)
    return res


@pg.production("statement : FOR variables_list IN expressions_list COLON suite")
def statement(state, p):
    pos, loop_var, source, suite = state.pos(p[0]), p[1], p[3], p[5]
    res = ast.For(pos, loop_var, source, suite)
    return res


@pg.production("statement : WHILE expression COLON suite")
def statement(state, p):
    pos, cond, suite = state.pos(p[0]), p[1], p[3]
    res = ast.While(pos, cond, suite)
    return res


@pg.production("statement : if")
def statement(state, p):
    return p[0]


@pg.production("if : IF expression COLON suite")
def if_(state, p):
    pos, parts = state.pos(p[0]), [{"cond": p[1], "suite": p[3]}]
    res = ast.If(pos, parts)
    return res


@pg.production("if : IF expression COLON suite ELSE COLON suite")
def if_(state, p):
    pos, parts = state.pos(p[0]), [{"cond": p[1], "suite": p[3]}, {"cond": None, "suite": p[6]}]
    res = ast.If(pos, parts)
    return res


@pg.production("if : IF expression COLON suite elifs")
def if_(state, p):
    pos, parts = state.pos(p[0]), [{"cond": p[1], "suite": p[3]}] + p[4]
    res = ast.If(pos, parts)
    return res


@pg.production("if : IF expression COLON suite elifs ELSE COLON suite")
def if_(state, p):
    pos, parts = state.pos(p[0]), [{"cond": p[1], "suite": p[3]}] + p[4] + [{"cond": None, "suite": p[7]}]
    res = ast.If(pos, parts)
    return res


@pg.production("elifs : elifs elif")
def elifs(state, p):
    p[0].append(p[1])
    return p[0]


@pg.production("elifs : elif")
def elifs(state, p):
    return [p[0]]


@pg.production("elif : ELIF expression COLON suite")
def elif_(state, p):
    return {"cond": p[1], "suite": p[3]}


@pg.production("statement : local_variables_declaration")
def statement(state, p):
    return p[0]


@pg.production("local_variables_declaration : VAR variables_list ASSIGN assignments NEW_LINE")
def local_variables_declaration(state, p):
    pos, variables, values = p[1].pos, p[1], p[3]
    res = ast.VariableDeclaration(pos, variables, ast.Assign(pos, variables, values))
    return res


@pg.production("local_variables_declaration : VAR variables_list ASSIGN expressions_list NEW_LINE")
def local_variables_declaration(state, p):
    pos, variables, values = p[1].pos, p[1], p[3]
    res = ast.VariableDeclaration(pos, variables, ast.Assign(pos, variables, values))
    return res


@pg.production("local_variables_declaration : VAR variables_list NEW_LINE")
def local_variables_declaration(state, p):
    pos, variables = p[1].pos, p[1]
    res = ast.VariableDeclaration(pos, variables)
    return res


@pg.production("variables_list : variables")
def variables_list(state, p):
    pos, elements = p[0][0].pos, p[0]
    if len(elements) == 1:
        res = elements[0]
    else:
        res = ast.Tuple(pos, elements)
    return res


@pg.production("variables : variables COMMA variable")
def variables(state, p):
    p[0].append(p[2])
    return p[0]


@pg.production("variables : variable")
def variables(state, p):
    return [p[0]]


@pg.production("variable : identifier")
def variable(state, p):
    pos, identifier = p[0].pos, p[0].name
    res = ast.Symbol(pos, identifier)
    return res


@pg.production("variable : identifier COLON type")
def variable(state, p):
    pos, identifier, typ = p[0].pos, p[0].name, p[2]
    res = ast.Symbol(pos, identifier, typ)
    return res


@pg.production("statement : assignments NEW_LINE")
def statement(state, p):
    return p[0]


@pg.production("assignments : expressions_list ASSIGN assignments")
def assignments(state, p):
    return binary_op(state, ast.Assign, p)


@pg.production("assignments : assignment")
def assignments(state, p):
    return p[0]


@pg.production("assignment : expressions_list ASSIGN expressions_list")
def assignment(state, p):
    return binary_op(state, ast.Assign, p)


@pg.production("statement : expressions_list INPLACE_ADD expressions_list NEW_LINE")
def statement(state, p):
    operation = binary_op(state, ast.Add, p)
    return ast.Inplace(operation.pos, operation)


@pg.production("statement : expressions_list INPLACE_SUB expressions_list NEW_LINE")
def statement(state, p):
    operation = binary_op(state, ast.Sub, p)
    return ast.Inplace(operation.pos, operation)


@pg.production("statement : expressions_list INPLACE_MUL expressions_list NEW_LINE")
def statement(state, p):
    operation = binary_op(state, ast.Mul, p)
    return ast.Inplace(operation.pos, operation)


@pg.production("statement : expressions_list INPLACE_DIV expressions_list NEW_LINE")
def statement(state, p):
    operation = binary_op(state, ast.Div, p)
    return ast.Inplace(operation.pos, operation)


@pg.production("statement : expressions_list INPLACE_MOD expressions_list NEW_LINE")
def statement(state, p):
    operation = binary_op(state, ast.Mod, p)
    return ast.Inplace(operation.pos, operation)


@pg.production("statement : expressions_list INPLACE_FLOOR_DIV expressions_list NEW_LINE")
def statement(state, p):
    operation = binary_op(state, ast.FloorDiv, p)
    return ast.Inplace(operation.pos, operation)


@pg.production("statement : expressions_list INPLACE_POW expressions_list NEW_LINE")
def statement(state, p):
    operation = binary_op(state, ast.Pow, p)
    return ast.Inplace(operation.pos, operation)


@pg.production("statement : expressions_list INPLACE_SHIFT_LEFT expressions_list NEW_LINE")
def statement(state, p):
    operation = binary_op(state, ast.BwShiftLeft, p)
    return ast.Inplace(operation.pos, operation)


@pg.production("statement : expressions_list INPLACE_SHIFT_RIGHT expressions_list NEW_LINE")
def statement(state, p):
    operation = binary_op(state, ast.BwShiftRight, p)
    return ast.Inplace(operation.pos, operation)


@pg.production("statement : expressions_list INPLACE_BW_AND expressions_list NEW_LINE")
def statement(state, p):
    operation = binary_op(state, ast.BwAnd, p)
    return ast.Inplace(operation.pos, operation)


@pg.production("statement : expressions_list INPLACE_BW_OR expressions_list NEW_LINE")
def statement(state, p):
    operation = binary_op(state, ast.BwOr, p)
    return ast.Inplace(operation.pos, operation)


@pg.production("statement : expressions_list INPLACE_BW_XOR expressions_list NEW_LINE")
def statement(state, p):
    operation = binary_op(state, ast.BwXor, p)
    return ast.Inplace(operation.pos, operation)


@pg.production("statement : yield")
def statement(state, p):
    return p[0]


@pg.production("yield : YIELD expressions_list NEW_LINE")
def yield_(state, p):
    pos, value = state.pos(p[0]), p[1]
    res = ast.Yield(pos, value)
    return res


@pg.production("statement : return")
def statement(state, p):
    return p[0]


@pg.production("return : RETURN expressions_list NEW_LINE")
def return_(state, p):
    pos, value = state.pos(p[0]), p[1]
    res = ast.Return(pos, value)
    return res


@pg.production("return : RETURN NEW_LINE")
def return_(state, p):
    pos, value = state.pos(p[0]), None
    res = ast.Return(pos, value)
    return res


@pg.production("statement : RAISE expression NEW_LINE")
def statement(state, p):
    pos, value = state.pos(p[0]), p[1]
    res = ast.Raise(pos, value)
    return res


@pg.production("statement : DEL expression NEW_LINE")
def statement(state, p):
    pos, value = state.pos(p[0]), p[1]
    res = ast.Del(pos, value)
    return res


@pg.production("statement : BREAK NEW_LINE")
def statement(state, p):
    return ast.Break(state.pos(p[0]))


@pg.production("statement : CONTINUE NEW_LINE")
def statement(state, p):
    return ast.Continue(state.pos(p[0]))


@pg.production("statement : PASS NEW_LINE")
def statement(state, p):
    return ast.Pass(state.pos(p[0]))


@pg.production("statement : expression NEW_LINE")
def statement(state, p):
    return p[0]


@pg.production("types : types COMMA type")
def types(state, p):
    p[0].append(p[2])
    return p[0]


@pg.production("types : type")
def types(state, p):
    return [p[0]]


@pg.production("type : CALLABLE LESS_THAN LESS_THAN formal_types GREATER_THAN COMMA type GREATER_THAN")
def type_(state, p):
    pos, args_types, ret_type = state.pos(p[0]), p[3], p[6]
    res = ast.FunctionType(pos, ret_type, args_types)
    return res


@pg.production("formal_types : formal_types COMMA formal_type")
def formal_types(state, p):
    p[0].append(p[2])
    return p[0]


@pg.production("formal_types : formal_type")
def formal_types(state, p):
    return [p[0]]


@pg.production("formal_types : ")
def formal_types(state, p):
    return []


@pg.production("formal_type : type")
def formal_type(state, p):
    pos, typ = p[0].pos, p[0]
    res = ast.Argument(pos, "", typ)
    return res


@pg.production("formal_type : MUL identifier")
def formal_type(state, p):
    pos, name, typ = state.pos(p[0]), p[1].name, ast.VariadicArgs(state.pos(p[0]))
    res = ast.Argument(pos, "", typ)
    return res


@pg.production("type : TILDE type")
def type_(state, p):
    pos, value = state.pos(p[0]), p[1]
    res = ast.Mutable(pos, value)
    return res


@pg.production("type : AMP type")
def type_(state, p):
    pos, value = state.pos(p[0]), p[1]
    res = ast.Reference(pos, value)
    return res


@pg.production("type : identifier LESS_THAN types GREATER_THAN")
def type_(state, p):
    pos, typ, type_vars = p[0].pos, p[0], p[2]
    res = ast.DerivedType(pos, typ.name, type_vars)
    return res


@pg.production("type : identifier")
def type_(state, p):
    pos, typ = p[0].pos, p[0]
    res = ast.Type(pos, typ.name)
    return res


@pg.production("expressions_list : expression")
def expressions_list(state, p):
    return p[0]


@pg.production("expressions_list : tuple")
def expressions_list(state, p):
    return p[0]


@pg.production("expression : list")
def expression(state, p):
    return p[0]


@pg.production("list : L_BRACKET list_items R_BRACKET")
def list_(state, p):
    pos, elements = state.pos(p[0]), p[1]
    res = ast.List(pos, elements=elements)
    return res


@pg.production("list_items : tuple")
def list_items(state, p):
    return p[0].elements


@pg.production("list_items : expression")
def list_items(state, p):
    return [p[0]]


@pg.production("list_items : ")
def list_items(state, p):
    return []


@pg.production("expression : set")
def expression(state, p):
    return p[0]


@pg.production("set : L_BRACE set_items R_BRACE")
def set_(state, p):
    pos, elements = state.pos(p[0]), p[1]
    res = ast.Set(pos, elements=elements)
    return res


@pg.production("set_items : tuple")
def set_items(state, p):
    return p[0].elements


@pg.production("set_items : expression")
def set_items(state, p):
    return [p[0]]


@pg.production("expression : dict")
def expression(state, p):
    return p[0]


@pg.production("dict : L_BRACE dict_items R_BRACE")
def dict_(state, p):
    pos, elements = state.pos(p[0]), p[1]
    res = ast.Dict(pos, elements=elements)
    return res


@pg.production("dict_items : dict_items COMMA dict_item")
def dict_items(state, p):
    p[0].update(p[2])
    return p[0]


@pg.production("dict_items : dict_item")
def dict_items(state, p):
    return p[0]


@pg.production("dict_items : ")
def dict_items(state, p):
    return {}


@pg.production("dict_item : literal COLON expression")
def dict_item(state, p):
    pos, key, value = state.pos(p[1]), p[0], p[2]
    return {key: value}


@pg.production("expression : L_PAREN tuple R_PAREN")
def expression(state, p):
    return p[1]


@pg.production("tuple : tuple COMMA expression")
def tuple_(state, p):
    p[0].elements.append(p[2])
    return p[0]


@pg.production("tuple : expression COMMA expression")
def tuple_(state, p):
    pos, element1, element2 = p[0].pos, p[0], p[2]
    res = ast.Tuple(pos, [element1, element2])
    return res


@pg.production("expression : AMP expression")
def expression(state, p):
    pos, value = state.pos(p[0]), p[1]
    res = ast.Reference(pos, value)
    return res


@pg.production("expression : MUL expression")
def expression(state, p):
    pos, value = state.pos(p[0]), p[1]
    res = ast.Dereference(pos, value)
    return res


@pg.production("expression : expression IF expression ELSE expression", precedence="IF")
def expression(state, p):
    pos, cond, values = state.pos(p[1]), p[2], [p[0], p[4]]
    res = ast.Ternary(pos, cond, values)
    return res


@pg.production("expression : L_PAREN expression R_PAREN")
def expression(state, p):
    return p[1]


@pg.production("expression : expression L_PAREN actuals R_PAREN")
def expression(state, p):
    pos, callable, args = state.pos(p[1]), p[0], p[2]
    if isinstance(callable, ast.Symbol):
        if callable.name == "array" and callable.derivation_types is not None:
            check_num_arguments(pos, 1, len(args))
            typ = callable.derivation_types[0]
            num_elements = args[0]
            res = ast.Array(pos, typ, num_elements)
            return res
        elif callable.name == "resize":
            check_num_arguments(pos, 2, len(args))
            obj, num_elements = args
            res = ast.Assign(pos, obj, ast.ReallocMemory(pos, obj, num_elements))
            return res
        elif callable.name == "offset":
            check_num_arguments(pos, 2, len(args))
            obj, idx = args
            res = ast.Offset(pos, obj, idx)
            return res
        elif callable.name in ["copymemory", "movememory"]:
            check_num_arguments(pos, 3, len(args))
            src, dst, num_elements = args
            if callable.name == "copymemory":
                res = ast.CopyMemory(pos, src, dst, num_elements)
            else:
                res = ast.MoveMemory(pos, src, dst, num_elements)
            return res
        elif callable.name in MAGIC_METHODS:
            check_num_arguments(pos, 1, len(args))
            obj, method = args[0], MAGIC_METHODS[callable.name]
            callable = ast.Attribute(pos, obj, method)
            args = args[1:]
    res = ast.Call(pos, callable, args)
    return res


@pg.production("actuals : actuals COMMA actual")
def actuals(state, p):
    p[0].append(p[2])
    return p[0]


@pg.production("actuals : actual")
def actuals(state, p):
    return [p[0]]


@pg.production("actuals : ")
def actuals(state, p):
    return []


@pg.production("actual : identifier ASSIGN expression")
def actual(state, p):
    pos, name, val = p[0].pos, p[0].name, p[2]
    res = ast.NamedArg(pos, name, val)
    return res


@pg.production("actual : expression")
def actual(state, p):
    return p[0]


@pg.production("expression : ISINSTANCE L_PAREN expression COMMA instance_types R_PAREN")
def expression(state, p):
    pos, obj, types = state.pos(p[1]), p[2], p[4]
    res = ast.IsInstance(pos, obj, types)
    return res


@pg.production("instance_types : L_PAREN types R_PAREN")
def instance_types(state, p):
    return p[1]


@pg.production("instance_types : type")
def instance_types(state, p):
    return [p[0]]


@pg.production("expression : expression DOT LESS_THAN types GREATER_THAN")
def expression(state, p):
    pos, obj, derivation_types = p[0].pos, p[0], p[3]
    obj.derivation_types = derivation_types
    return obj


@pg.production("expression : SIZEOF L_PAREN type R_PAREN")
def expression(state, p):
    pos, typ = state.pos(p[1]), p[2]
    res = ast.SizeOf(pos, typ)
    return res


@pg.production("expression : TRANSMUTE L_PAREN expression COMMA type R_PAREN")
def expression(state, p):
    pos, obj, type = state.pos(p[1]), p[2], p[4]
    res = ast.Transmute(pos, obj, type)
    return res


@pg.production("expression : NOT expression")
def expression(state, p):
    return unary_op(state, ast.Not, p)


@pg.production("expression : expression AND expression")
def expression(state, p):
    return binary_op(state, ast.And, p)


@pg.production("expression : expression OR expression")
def expression(state, p):
    return binary_op(state, ast.Or, p)


@pg.production("expression : TILDE expression")
def expression(state, p):
    return unary_op(state, ast.BwNot, p)


@pg.production("expression : expression AMP expression")
def expression(state, p):
    return binary_op(state, ast.BwAnd, p)


@pg.production("expression : expression PIPE expression")
def expression(state, p):
    return binary_op(state, ast.BwOr, p)


@pg.production("expression : expression CARET expression")
def expression(state, p):
    return binary_op(state, ast.BwXor, p)


@pg.production("expression : expression LESS_THAN LESS_THAN expression")
def expression(state, p):
    left, op, right = p[0], p[1], p[3]
    return binary_op(state, ast.BwShiftLeft, (left, op, right))


@pg.production("expression : expression GREATER_THAN GREATER_THAN expression")
def expression(state, p):
    left, op, right = p[0], p[1], p[3]
    return binary_op(state, ast.BwShiftRight, (left, op, right))


@pg.production("expression : expression IS expression")
def expression(state, p):
    return binary_op(state, ast.Is, p)


@pg.production("expression : expression IN expression")
def expression(state, p):
    return binary_op(state, ast.In, p)


@pg.production("expression : expression EQUAL expression")
def expression(state, p):
    return binary_op(state, ast.Equal, p)


@pg.production("expression : expression NOT_EQUAL expression")
def expression(state, p):
    return binary_op(state, ast.NotEqual, p)


@pg.production("expression : expression LESS_THAN expression")
def expression(state, p):
    return binary_op(state, ast.LowerThan, p)


@pg.production("expression : expression LESS_EQUAL expression")
def expression(state, p):
    return binary_op(state, ast.LowerEqual, p)


@pg.production("expression : expression GREATER_THAN expression")
def expression(state, p):
    return binary_op(state, ast.GreaterThan, p)


@pg.production("expression : expression GREATER_EQUAL expression")
def expression(state, p):
    return binary_op(state, ast.GreaterEqual, p)


@pg.production("expression : MINUS expression")
def expression(state, p):
    return unary_op(state, ast.Neg, p)


@pg.production("expression : expression PLUS expression")
def expression(state, p):
    return binary_op(state, ast.Add, p)


@pg.production("expression : expression MINUS expression")
def expression(state, p):
    return binary_op(state, ast.Sub, p)


@pg.production("expression : expression MUL expression")
def expression(state, p):
    pos, left, right = state.pos(p[1]), p[0], p[2]

    def list_initializer(pos, lst, num_elements):
        if not isinstance(num_elements, ast.Int):
            msg = (num_elements.pos, "the number of elements must be a literal integer")
            raise util.Error([msg])
        else:
            if len(lst.elements) == 1:
                default_value = lst.elements[0]
                pos = default_value.pos
            else:
                default_value = None
                pos = lst.pos
            if default_value is None or \
                    not isinstance(default_value, (ast.NoneVal, ast.Byte, ast.Bool, ast.Int, ast.Float, ast.String)):
                msg = (pos, "the default value must be a literal value between brackets")
                raise util.Error([msg])
        return ast.List(pos, [default_value] * num_elements.literal)

    # Handle list initialization like: [x] * num_elements
    if isinstance(left, ast.List):
        return list_initializer(pos, left, right)
    elif isinstance(right, ast.List):
        return list_initializer(pos, right, left)

    # Handle basis multiplication operation
    else:
        return binary_op(state, ast.Mul, p)


@pg.production("expression : expression DIV expression")
def expression(state, p):
    return binary_op(state, ast.Div, p)


@pg.production("expression : expression FLOOR_DIV expression")
def expression(state, p):
    return binary_op(state, ast.FloorDiv, p)


@pg.production("expression : expression MOD expression")
def expression(state, p):
    return binary_op(state, ast.Mod, p)


@pg.production("expression : expression POW expression")
def expression(state, p):
    return binary_op(state, ast.Pow, p)


@pg.production("expression : expression AS type")
def expression(state, p):
    return binary_op(state, ast.As, p)


@pg.production("expression : attribute")
def expression(state, p):
    return p[0]


@pg.production("attribute : expression DOT identifier")
def attribute(state, p):
    pos, obj, attribute = state.pos(p[1]), p[0], p[2].name
    res = ast.Attribute(pos, obj, attribute)
    return res


@pg.production("expression : element")
def expression(state, p):
    return p[0]


@pg.production("element : expression L_BRACKET expression R_BRACKET")
def element(state, p):
    pos, obj, key = state.pos(p[1]), p[0], p[2]
    res = ast.Element(pos, obj, key)
    return res


@pg.production("expression : identifier")
def expression(state, p):
    pos, identifier = p[0].pos, p[0].name
    res = ast.Symbol(pos, identifier)
    return res


@pg.production("expression : literal")
def expression(state, p):
    return p[0]


@pg.production("literals : literals COMMA literal")
def literals(state, p):
    p[0].append(p[2])
    return p[0]


@pg.production("literals : literal")
def literals(state, p):
    return [p[0]]


@pg.production("literal : string")
def literal(state, p):
    return p[0]


@pg.production("literal : multiline_string")
def literal(state, p):
    pos, string = p[0].pos, p[0].literal
    return ast.String(pos, string)


@pg.production("literal : CHAR")
def literal(state, p):
    pos, char = state.pos(p[0]), p[0].value
    return ast.Byte(pos, char)


@pg.production("literal : BOOL")
def literal(state, p):
    pos, boolean = state.pos(p[0]), p[0].value
    return ast.Bool(pos, boolean)


@pg.production("literal : HEX")
def literal(state, p):
    pos, number = state.pos(p[0]), int(p[0].value, 0)
    return ast.Int(pos, number)


@pg.production("literal : OCT")
def literal(state, p):
    pos, number = state.pos(p[0]), int(p[0].value, 0)
    return ast.Int(pos, number)


@pg.production("literal : BIN")
def literal(state, p):
    pos, number = state.pos(p[0]), int(p[0].value, 2)
    return ast.Int(pos, number)


@pg.production("literal : FLOAT")
def literal(state, p):
    pos, number = state.pos(p[0]), p[0].value
    return ast.Float(pos, number)


@pg.production("literal : INT")
def literal(state, p):
    pos, number = state.pos(p[0]), p[0].value
    return ast.Int(pos, number)


@pg.production("literal : NONE")
def literal(state, p):
    return ast.NoneVal(state.pos(p[0]))


@pg.production("string : STRING")
def string(state, p):
    pos, string = state.pos(p[0]), p[0].value[1:-1]
    return ast.String(pos, string)


@pg.production("multiline_string : MULTILINE_STRING")
def multiline_string(state, p):
    pos, string = state.pos(p[0]), p[0].value[3:-3]
    return ast.MultilineString(pos, string)


@pg.production("identifiers : identifiers COMMA identifier")
def identifiers(state, p):
    p[0].append(p[2])
    return p[0]


@pg.production("identifiers : identifier")
def identifiers(state, p):
    return [p[0]]


@pg.production("identifier : IDENTIFIER")
def identifier(state, p):
    res = ast.Name(state.pos(p[0]), p[0].value)
    return res


@pg.error
def error(state, token):

    # Use the last non-ignorable token before line break
    if token.name == "NEW_LINE":
        token = token.last_valid_token

    msg = (state.pos(token), "invalid syntax")
    raise util.Error([msg])


PARSER = pg.build()


class State(object):

    def __init__(self, file, src):
        self.file = file
        self.src = src
        self.lines = src.splitlines()

    def pos(self, token):
        """
        Reprocess location information (see parse() for more details).
        """
        ln = token.source_pos.lineno - 1
        col = token.source_pos.colno - 1
        line = self.lines[ln] if ln < len(self.lines) else ""
        return (ln, col), (ln, col + len(token.value)), line, self.file


def parse(src, state):
    """
    Takes a file name and returns the AST (abstract syntax tree) corresponding to the source contained in the file.
    The State thing is here mostly to reprocess location information from rply into something easier to use. AST nodes
    get a pos field containing a 4-element tuple:

    - Tuple of start location, as 0-based line and column numbers
    - Tuple of end location, as 0-based line and column numbers
    - The full line
    - The file name

    This should be everything we need to build good error messages.
    """
    try:
        tokens = lex(src, state)
    except rply.LexingError as e:

        # Fix the RPLY column number bug, counting the number of characters from token index until the previous
        # line break
        i = e.source_pos.idx
        col_count = 0
        while i >= 0:
            if src[i] == "\n":
                break
            i -= 1
            col_count += 1

        token = e
        token.value = ""
        token.source_pos.colno = col_count
        pos = state.pos(token)
        msg = (pos, "invalid syntax")
        hints = ["Check whether there is a typo in the name."]
        raise util.Error([msg], hints=hints)

    return PARSER.parse(tokens, state=state)
