"""
AndroidPermissions

The aim of this project was to analyze all the Android codebase in order to build a complete list of:
- which methods require a specific Android permission,
- methods that are marked as unsupported or unsafe.

An inspiration for this project was the very good repository from Erik Derr (reddr),
called "axplorer - Android Permission Mappings" (https://github.com/reddr/axplorer).
It claim to be a project for a static analysis tool to study Android's application framework's internals,
but source code hasn't been released yet.
Erik only released the Android permission/methods mappings from API levels 16 (4.1) to 25 (7.1).

My purpose was to build a tool capable of generating the same mappings.

Unfortunately, this project is incomplete because it has many limitation:
- It is written in Python. Now consider to analyze all the Android source code...
- It uses a library to parse the Java source code and build an AST. Waste of time...
- As Erik wrote in his repo, Android 23+ allows Runtime permission checks.
- Android NDK allows you to check permission directly in native code.

"""

import javalang
from javalang.tree import Node, Annotation, PackageDeclaration, ClassDeclaration, MethodInvocation, MethodDeclaration, \
    FieldDeclaration

from typing import Any, List, Tuple, Union


class RequiresPermission:
    def __init__(self, name="", qualifier="", isMethod=True, permissions=None, needsAllOf=False):
        self.name = name
        self.qualifier = qualifier
        self.isMethod = isMethod

        self.permissions = [] if not permissions else permissions
        self.needsAllOf = needsAllOf

    def __str__(self):
        return self.__repr__()

    def __repr__(self):
        return " - ".join(["%s(%s)" % (x, self.__getattribute__(x)) for x in self.__dir__()
                           if not x.startswith("_")])


class UnsupportedAppUsage:
    def __init__(self, name="", qualifier="", isMethod=True, minTargetSdk=0, maxTargetSdk=0, deprecationNote=""):
        self.name = name
        self.qualifier = qualifier
        self.isMethod = isMethod

        self.minTargetSdk = minTargetSdk
        self.maxTargetSdk = maxTargetSdk
        self.deprecationNote = deprecationNote

    def __str__(self):
        return self.__repr__()

    def __repr__(self):
        return " - ".join(["%s(%s)" % (x, self.__getattribute__(x)) for x in self.__dir__()
                           if not x.startswith("_")])


def get_name_and_qualifier(element: Node, qualifier: List[str]) -> Tuple[str, str]:
    if isinstance(element, MethodDeclaration):
        parameters = []
        if "parameters" in element.attrs and len(element.parameters):
            for p in element.parameters:
                parameters.append("%s %s" % (p.type.name, p.name))

        return_type = None
        if "return_type" in element.attrs and element.return_type:
            return_type = element.return_type.name
            if "arguments" in element.return_type.attrs and element.return_type.arguments:
                return_type += "<" + ", ".join(r.type.name for r in element.return_type.arguments) + ">"

        return element.name, \
               ".".join(qualifier) + "(" + ", ".join(parameters) + ") -> " + \
               (return_type if return_type else "void")

    if not element.declarators or len(element.declarators) > 1:
        breakpoint()
        # TODO
        return "", ""

    return element.declarators[0].name, ".".join(qualifier + [element.declarators[0].name]) + " -> " + \
           element.type.name


def parse_requirements(element: Node, annotation: Annotation, qualifier: List[str]) -> RequiresPermission:
    name, element_qualifier = get_name_and_qualifier(element, qualifier)
    target = RequiresPermission(name, element_qualifier, isMethod=isinstance(element, MethodDeclaration))

    if "element" in annotation.attrs and annotation.element:
        if isinstance(annotation.element, list):
            for elm in annotation.element:
                setattr(target, "needsAllOf", elm.name == "allOf")
                for val in elm.value.values:
                    target.permissions.append(val.qualifier + "." + val.member)

        else:
            target.permissions.append(annotation.element.qualifier + "." + annotation.element.member)

    return target


def parse_deprecation(element: Node, annotation: Annotation, qualifier: List[str]) -> UnsupportedAppUsage:
    name, element_qualifier = get_name_and_qualifier(element, qualifier)
    target = UnsupportedAppUsage(name, element_qualifier, isMethod=isinstance(element, MethodDeclaration))

    if "element" in annotation.attrs and annotation.element:
        if isinstance(annotation.element, list):
            for elm in annotation.element:
                if elm.name == "minTargetSdk" or elm.name == "maxTargetSdk":
                    setattr(target, elm.name, elm.value.qualifier + "." + elm.value.member)

        else:
            if annotation.element.name == "minTargetSdk" or annotation.element.name == "maxTargetSdk":
                setattr(target, annotation.element.name, annotation.element.value.qualifier + "." +
                        annotation.element.value.member)

    if element.documentation and len(element.documentation):
        deprecation_in_doc = element.documentation.find("@deprecated")
        if deprecation_in_doc > 0:
            deprecation_doc_text = "".join(x.replace("*", "").replace("/", "").strip()
                                           for x in element.documentation[deprecation_in_doc:].split("\n"))
            setattr(target, "deprecationNote", deprecation_doc_text)

    return target


def parse_element_annotations(element: Node, qualifier: List[str]) -> \
        List[Union[RequiresPermission, UnsupportedAppUsage]]:
    partial = []

    if len(element.annotations):
        for annotation in element.annotations:
            if annotation.name == "UnsupportedAppUsage":
                partial.append(parse_deprecation(element, annotation, qualifier))

            elif annotation.name == "RequiresPermission":
                partial.append(parse_requirements(element, annotation, qualifier))

    return partial


def parse_method_invocation(element: Node, qualifier: List[str]) -> Union[RequiresPermission, None]:
    if element.member in ["enforceCallingOrSelfPermission"]:  # TODO... all...
        print("ENFORCING")
        breakpoint()
        pass

    return


def son_of_a_class(children: List[Any], qualifier: List[str]) -> List[Union[RequiresPermission, UnsupportedAppUsage]]:
    partial = []
    for child in children:
        if isinstance(child, PackageDeclaration):
            qualifier = [child.name]

        elif isinstance(child, ClassDeclaration):
            qualifier.append(child.name)

        elif isinstance(child, MethodDeclaration):
            qualifier.append(child.name)
            partial += parse_element_annotations(child, qualifier)

        elif isinstance(child, FieldDeclaration):
            partial += parse_element_annotations(child, qualifier)

        elif isinstance(child, MethodInvocation):
            method_output = parse_method_invocation(child, qualifier)
            if method_output:
                partial.append(method_output)

        elif isinstance(child, list):
            partial += son_of_a_class(child, qualifier)

        if hasattr(child, "children") and len(child.children):
            partial += son_of_a_class(child.children, qualifier)
            if isinstance(child, ClassDeclaration) or isinstance(child, MethodDeclaration):
                qualifier.pop()

    return partial


def analyze(file: str) -> List[Union[RequiresPermission, UnsupportedAppUsage]]:
    annotations = []

    with open(file) as f:
        file_content = f.read()
        if "UnsupportedAppUsage" in file_content or \
                "RequiresPermission" in file_content or "Manifest.permission." in file_content:
            # TODO: Maybe the "Manifest.permission" check makes it useless the "RequiresPermission" one...
            tokens = javalang.tokenizer.tokenize(file_content)
            tree = javalang.parser.Parser(tokens)
            annotations = son_of_a_class(tree.parse().children, qualifier=[])

    return annotations


if __name__ == "__main__":
    import glob

    for f in glob.glob("test_files/*.java"):
        print("###", f, "###")
        output = analyze(f)
        print("\n".join(str(x) for x in output))
