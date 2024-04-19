import os
import re
import inspect
import ayon_api
from ayon_api import ServerAPI

EXCLUDED_METHODS = {
    "get_default_service_username",
    "validate_token",
    "set_token",
    "reset_token",
    "create_session",
    "close_session",
    "as_username",
    "validate_server_availability",
    "get_headers",
    "login",
    "logout",
    "set_default_service_username",
}
EXCLUDED_IMPORT_NAMES = {"GlobalContext"}
AUTOMATED_COMMENT = "\n".join((
    "# ------------------------------------------------",
    "#     This content is generated automatically.",
    "# ------------------------------------------------",
))


# Read init file and remove ._api imports
def prepare_init_without_api(init_filepath):
    with open(init_filepath, "r") as stream:
        content = stream.read()

    api_regex = re.compile("from \._api import \((?P<functions>[^\)]*)\)")
    api_imports = api_regex.search(content)
    start, end = api_imports.span()
    api_imports_text = content[start:end]
    functions_text = api_imports.group("functions")
    function_names = [
        line.strip().rstrip(",")
        for line in functions_text.split("\n")
        if line.strip()
    ]
    function_names_q = {
        f'"{name}"' for name in function_names
    }

    all_regex = re.compile("__all__ = \([^\)]*\)")
    all_content = all_regex.search(content)
    start, end = all_content.span()
    all_content_text = content[start:end]
    filtered_lines = []
    for line in content[start:end].split("\n"):
        found = False
        for name in function_names_q:
            if name in line:
                found = True
                break
        if not found:
            filtered_lines.append(line)
    new_all_content_text = (
        "\n".join(filtered_lines).rstrip(") \n") + "\n\n{all_content}\n)"
    )

    formatting_content = (
        content
        .replace(api_imports_text, "{api_imports}")
        .replace(all_content_text, new_all_content_text)
    ).rstrip("\n")
    tmp_init = formatting_content.format(all_content="", api_imports="")
    with open(init_filepath, "w") as stream:
        print(tmp_init, file=stream)
    return formatting_content

# Creation of _api.py content
def indent_lines(src_str, indent=1):
    new_lines = []
    for line in src_str.split("\n"):
        if line:
            line = f"{'    ' * indent}{line}"
        new_lines.append(line)
    return "\n".join(new_lines)


def split_sig_str(sig_str):
    args_str = sig_str[1:-1]
    args = [f"    {arg.strip()}" for arg in args_str.split(",")]
    joined_args = ",\n".join(args)

    return f"(\n{joined_args}\n)"


def prepare_func_def_line(attr_name, sig_str):
    return f"def {attr_name}{sig_str}:\n"


def prepare_docstring(func):
    docstring = inspect.getdoc(func)
    if not docstring:
        return ""

    line_char = ""
    if "\n" in docstring:
        line_char = "\n"
    return f'"""{docstring}{line_char}\n"""'


def prapre_body_sig_str(sig_str):
    if "=" not in sig_str:
        return sig_str

    args_str = sig_str[1:-1]
    args = []
    for arg in args_str.split(","):
        arg = arg.strip()
        if "=" in arg:
            parts = arg.split("=")
            parts[1] = parts[0]
            arg = "=".join(parts)
        args.append(arg)
    joined_args = ", ".join(args)
    return f"({joined_args})"


def prepare_body_parts(attr_name, sig_str):
    output = [
        "con = get_server_api_connection()",
    ]
    body_sig_str = prapre_body_sig_str(sig_str)
    return_str = f"return con.{attr_name}{body_sig_str}"
    if len(return_str) + 4 <= 79:
        output.append(return_str)
        return output

    return_str = f"return con.{attr_name}{split_sig_str(body_sig_str)}"
    output.append(return_str)
    return output


def prepare_api_functions():
    functions = []
    for attr_name, attr in ServerAPI.__dict__.items():
        if (
            attr_name.startswith("_")
            or attr_name in EXCLUDED_METHODS
            or not callable(attr)
        ):
            continue

        sig = inspect.signature(attr)
        base_sig_str = str(sig)
        if base_sig_str == "(self)":
            sig_str = "()"
        else:
            sig_str = "(*args, **kwargs)"

        func_def = prepare_func_def_line(attr_name, sig_str)

        func_body_parts = []
        docstring = prepare_docstring(attr)
        if docstring:
            func_body_parts.append(docstring)

        func_body_parts.extend(prepare_body_parts(attr_name, sig_str))

        func_body = indent_lines("\n".join(func_body_parts))
        full_def = func_def + func_body
        functions.append(full_def)
    return "\n\n\n".join(functions)


def main():
    # TODO order methods in some order
    dirpath = os.path.dirname(os.path.dirname(
        os.path.abspath(ayon_api.__file__)
    ))
    ayon_api_root = os.path.join(dirpath, "ayon_api")
    init_filepath = os.path.join(ayon_api_root, "__init__.py")
    api_filepath = os.path.join(ayon_api_root, "_api.py")
    formatting_init_content = prepare_init_without_api(init_filepath)

    result = prepare_api_functions()
    with open(api_filepath, "r") as stream:
        old_content = stream.read()

    parts = old_content.split(AUTOMATED_COMMENT)
    if len(parts) == 1:
        raise RuntimeError(
            "Automated comment not found in '_api.py'"
        )
    if len(parts) > 2:
        raise RuntimeError(
            "Automated comment found multiple times in '_api.py'"
        )

    new_content = f"{parts[0]}{AUTOMATED_COMMENT}\n{result}"
    with open(api_filepath, "w") as stream:
        print(new_content, file=stream)

    # find all functions and classes available in '_api.py'
    func_regex = re.compile("^(def|class) (?P<name>[^\(]*)(\(|:).*")
    func_names = []
    for line in new_content.split("\n"):
        result = func_regex.search(line)
        if result:
            name = result.group("name")
            if name.startswith("_") or name in EXCLUDED_IMPORT_NAMES:
                continue
            func_names.append(name)

    import_lines = ["from ._api import ("]
    for name in func_names:
        import_lines.append(f"    {name},")
    import_lines.append(")")

    all_lines = [
        f'    "{name}",'
        for name in func_names
    ]
    new_init_content = formatting_init_content.format(
        api_imports="\n".join(import_lines),
        all_content="\n".join(all_lines),
    )

    with open(init_filepath, "w") as stream:
        print(new_init_content, file=stream)


if __name__ == "__main__":
    main()