def format(s, **args_dict):
    buffer = ""
    args_list = list(args_dict.values())

    i = 0
    arg_idx = 0
    while i < len(s):  # while s[i] != "\0"

        # A new argument was found
        if s[i] == '{':
            i += 1

            # Reset the argument elements
            id_is_numeric = False
            id = ""
            width = 0
            precision = 0
            flag = ""

            # Try get a numeric id of the argument
            while '0' <= s[i] <= '9':
                id += s[i]
                i += 1

            # Try get an alphanumeric id if first attempt fail
            if id == "":
                while ('A' <= s[i] <= 'z') or ('0' <= s[i] <= '9') or s[i] == '_':
                    id += s[i]
                    i += 1
            else:
                id_is_numeric = True

            # Try get the argument format
            if s[i] == ':':
                i += 1

                # Try get the width of the number
                w = ""
                while '0' <= s[i] <= '9':
                    w += s[i]
                    i += 1
                if w != "":
                    width = int(w)

                # Try get the precision of the number
                p = ""
                if s[i] == '.':
                    i += 1
                    while '0' <= s[i] <= '9':
                        p += s[i]
                        i += 1
                if p != "":
                    precision = int(p)
                else:
                    precision = 6  # Default precision if not specified

                # Try get the type of argument
                if s[i] == 'd' or s[i] == 'f':
                    flag = s[i]
                    i += 1

            # Mount the formatted argument
            if s[i] == '}':
                i += 1

                # Get the value to be formatted
                if id != "":
                    if id_is_numeric:
                        v = args_list[int(id)]
                    else:
                        v = args_dict[id]
                else:
                    v = args_list[arg_idx]

                # Check if the argument type is correct
                if flag == "d":
                    format_type = "int"
                elif flag == "f":
                    format_type = "float"
                else:
                    format_type = ""
                if format_type != "":
                    if isinstance(v, int):
                        arg_type = "int"
                    elif isinstance(v, float):
                        arg_type = "float"
                    else:
                        arg_type = ""
                    if arg_type != format_type:
                        raise Exception("format specifies type '" + format_type +
                                        "' but the argument has type '" + arg_type + "'")
                value = str(v)

                if flag == "d" or flag == "f":

                    # Mount the number and its digits
                    number, number_len, digits, digits_len, dot_found = "", 0, "", 0, False
                    j = 0
                    value_len = len(value)
                    while j < value_len:  # value[j] != '\0'
                        if value[j] == '.':
                            dot_found = True
                        elif dot_found:
                            if digits_len < precision:
                                digits += value[j]
                                digits_len += 1
                                # TODO: Round the digit in case of the formatted value have less digits than original value
                        else:
                            if width == 0 or number_len < width:
                                number += value[j]
                                number_len += 1
                        j += 1

                    if width > 0:
                        # Fill number until it reach fixed width
                        while number_len < width:
                            number = " " + number
                            number_len += 1
                    buffer += number

                    if precision > 0:
                        # Fill digits until it reach fixed precision
                        while digits_len < precision:
                            digits += "0"
                            digits_len += 1
                        buffer += "." + digits
                else:
                    buffer += value

                arg_idx += 1
            else:
                raise Exception("expected '}' but '" + s[i] + "' was found")
        else:
            buffer += s[i]
            i += 1

    return buffer

print(format("{0}, {1:10d}, {c:6.3f}, {:.2f}", a="test", b=12, c=1234.56, d=123.456))
print(format("{:f}", a=123.4567890123))
