import sys
import re
import sublime
import sublime_plugin

from .user_templates import *

__all__ = [
    "PhpGenerateGetterForCommand",
    "PhpGenerateSetterForCommand",
    "PhpGenerateGetterSetterForCommand",
    "PhpGenerateGettersCommand",
    "PhpGenerateSettersCommand",
    "PhpGenerateGettersSettersCommand",
    "PhpGenerateGettersSetterUnavailable",
    "plugin_loaded"
]

DEBUG = False

def msg(msg):
    if DEBUG:
        print("[PHP Getters and Setters] %s" % msg)

def prefs():
    return sublime.load_settings('PHP Getters Setters.sublime-settings')


class TemplateManager:
    templates = {}

    def register(self, template):
        self.templates[template.name] = template
        msg("Registered template : '%s'" % template.name)

    def get(self, name):
        return self.templates[name]

class Variable:
    def __init__(self, name, visibility, typeName=None, description=None):
        settings = prefs()
        self.name = name
        self.type = typeName
        self.description = description
        if settings.get("ignore_visibility", False):
            visibility = "public"
        self.visibility = visibility
        self.template = templateManager.get(settings.get("template"))
        self.style = self.template.style

    def getName(self):
        return self.name

    def getVisibility(self):
        return self.visibility

    def getVisibilityPrefix(self):
        visibility = self.visibility
        Prefix = ''

        if (visibility == 'private'):
            Prefix = '_'

        return Prefix

    def getParam(self):
        name = self.name

        if (name[0] == '_'):
            name = name[1:]

        return name

    def getHumanName(self):
        style = self.style
        name = self.getName()

        if 'camelCase' == style:
            # FIXME how does this differ from the else?
            name = ' '.join(re.findall(r'(?:[^_a-z]{0,2})[^_A-Z]+', name)).lower()
        else:
            name = name.replace('_', ' ')

        return name

    def getDescription(self):
        if self.description is None or "" == self.description:
            self.description = 'value of %s' % self.getName() # get description from name
        return self.description

    def getPartialFunctionName(self):
        style = self.style
        name = self.getName()
        length = len(name)

        if length > 1 and name[0] == '_' and name[1].islower() and name[2].isupper():
            name = name[2:]  # _aTest
        elif length > 1 and (name[0].islower() and name[1].isupper()):
            name = name[1:]  # aTest
        elif length > 1 and (name[0] == '_'):
            name = name[1:]  # _test OR _Test

        if 'camelCase' == style:
            var = re.sub(r'_([a-z])', lambda pat: pat.group(1).upper(), name)
            var = var[0].upper() + var[1:]
            var = var.replace("_", "")
        else:
            var = name

        return var

    def getGetterPrefix(self):
        return "is" if 'bool' in self.getType() else "get"

    def getGetterFunctionName(self):
        style = self.style
        getterPrefix = self.getGetterPrefix()

        if 'camelCase' == style:
            return getterPrefix + "%s" % self.getPartialFunctionName()

        return getterPrefix + "_%s" % self.getPartialFunctionName()

    def getSetterPrefix(self):
        return "set"

    def getSetterFunctionName(self):
        style = self.style
        visPrefix = self.getVisibilityPrefix()
        setterPrefix = self.getSetterPrefix()

        if 'camelCase' == style:
            return visPrefix + setterPrefix + "%s" % self.getPartialFunctionName()

        return visPrefix + setterPrefix + "_%s" % self.getPartialFunctionName()

    def getType(self):
        return self.type

    def getTypeHint(self):
        if self.type in prefs().get('type_hint_ignore', []):
            return ''

        if self.type.find(" ") > -1 or self.type.find(r"|") > -1:
            msg("'%s' is more than one type, switching to no type hint" % self.type)
            return ""

        return self.type


class DocBlock:
    """
        docblock text to a class
    """
    def __init__(self):
        self.tags = {}
        self.description = ''

    def hasTag(self, name):
        return name in self.tags

    def hasDescription(self):
        return len(self.description) > 0

    def addTag(self, name, value):
        self.tags[name] = value

    def getTag(self, name):
        if not self.hasTag(name):
            return None

        return self.tags[name]

    def setDescription(self, value):
        self.description = value

    def getDescription(self):
        return self.description

    def fromText(self, content):
        lines = content.split("\n")
        description = []

        for line in lines:
            line = line.strip(' \t*/').rstrip('.')
            if line.startswith('@'):
                nameMatches = re.findall(r'\@(\w+) (:?.*)[ ]?.*', line)
                if len(nameMatches) > 0:
                    name = nameMatches[0][0]
                    value = nameMatches[0][1]

                    self.addTag(name.strip('@'), value)
                # [name, value, other] = line.split(" ", 2)
                else:
                    msg("Error: could not parse line %s" % line)
            else:
                if len(line) > 0:
                    description.append(line)

        self.setDescription("\n".join(description).rstrip("\n"))


class Parser:
    """
        parses text to get class variables so that make the magic can happen
    """
    def __init__(self, content):
        self.content = content
        self.functionRegExp = r".*function.*%s\("
        self.variableRegExp = r'((?:private|public|protected)(?:[ ]+\S{0,}){0,2}[ ]{0,}(?:\$.*?)[ |=|;].*)\n'

    def getContent(self):
        return self.content

    def hasFunction(self, name):
        """
            returns true if the function with the name _name_ is found in the code
        """
        content = self.getContent()
        regExp = self.functionRegExp % name

        return re.search(regExp, content) is not None

    def _getDockBlockOfVariable(self, line):
        content = self.getContent()
        matchPos = content.find(line)

        lineByLine = content[:matchPos].split("\n")
        lineByLine.reverse()
        commentStart = 0
        commentEnd = 0

        for n in range(len(lineByLine)):
            line = lineByLine[n].strip()
            if "\n" == line:
                continue

            elif "\r\n" == line:
                continue

            elif "" == line:
                continue

            elif '*/' == line:
                commentStart = n + 1

            elif '/**' == line:
                commentEnd = n
                break

            elif 0 == commentStart:
                break

        if commentStart == commentEnd:
            return ""

        if commentStart == 0 or commentEnd == 0:
            return ""

        result = lineByLine[commentStart:commentEnd]
        result.reverse()

        return "\n".join(result)

    def _processVariable(self, line):
        """
            Returns a Variable object populated from the parsed code
        """
        nameMatches = re.findall(r'\$(.*?)[ |=|;]', line)
        name = "Unknown"
        if len(nameMatches) >= 0:
            name = nameMatches[0]

        visibility = 'public'
        visibilityMatches = re.findall(r'^(public|protected|private)', line)

        if len(visibilityMatches) >= 0:
            visibility = visibilityMatches[0]

        dockBlockText = self._getDockBlockOfVariable(line)
        docblock = DocBlock()
        docblock.fromText(dockBlockText)

        typeName = 'mixed'
        if docblock.hasTag('var'):
            typeName = docblock.getTag('var')
        description = docblock.getDescription()

        return Variable(name = name, visibility = visibility, typeName = typeName, description = description)

    def getClassVariables(self):
        """
            returns a list of Variable objects, created from the parsed code
        """
        content = self.getContent()
        variablesList = []

        matches = re.findall(self.variableRegExp, content,  re.IGNORECASE)
        for match in matches:
            variable = self._processVariable(match)
            variablesList.append(variable)

        return variablesList

class Base(sublime_plugin.TextCommand):
    def getContent(self):
        return self.view.substr(sublime.Region(0, self.view.size()))

    def findLastBracket(self):
        view = self.view
        pos = 0
        lastPos = 1

        pos = view.find(r'\{', 0)

        while True:
            pos = view.find(r'\}', pos.end())
            if (pos.begin() == -1):
                break
            lastPos = pos.begin()

        return lastPos

    def generateFunctionCode(self, template, variable):
        substitutions = {
            "name": variable.getName(),
            "param": variable.getParam(),
            "visibility": variable.getVisibility(),
            "visibilityPrefix": variable.getVisibilityPrefix(),
            "type": variable.getType(),
            "normalizedName": variable.getPartialFunctionName(),
            "description": variable.getDescription(),
            "typeHint": variable.getTypeHint(),
            "humanName": variable.getHumanName(),
            "getterPrefix": variable.getGetterPrefix(),
            "setterPrefix": variable.getSetterPrefix()
        }

        return template % substitutions

    def generateGetterFunction(self, parser, variable):

        if parser.hasFunction(variable.getGetterFunctionName()):
            msg("function %s already present, skipping" % variable.getGetterFunctionName())
            return ''

        template = templateManager.get(prefs().get('template', "PSR2"))
        code = self.generateFunctionCode(template.getter, variable)

        return code

    def generateSetterFunction(self, parser, variable):

        if parser.hasFunction(variable.getSetterFunctionName()):
            msg("function %s already present, skipping" % variable.getSetterFunctionName())
            return ''

        template = templateManager.get(prefs().get('template', "PSR2"))
        code = self.generateFunctionCode(template.setter, variable)
        # if type hinting is not to be show we get "( " instead of (
        code = code.replace('( ', '(')

        return code

    def writeAtEnd(self, edit, text):
        lastPos = self.findLastBracket()
        self.view.insert(edit, lastPos, text)

    def isPhpSyntax(self):
        sel = self.view.sel()
        if not sel:
            return False
        return self.view.match_selector(sel[0].b, "embedding.php, text.html.php")

    def is_enabled(self):
        return self.isPhpSyntax()

    def is_visible(self):
        return self.is_enabled()


class PhpGenerateFor(Base):
    what = 'getter'

    def run(self, edit):
        self.edit = edit

        parser = Parser(self.getContent())

        self.vars = []

        for variable in parser.getClassVariables():
            item = [variable.getName(), variable.getDescription()]
            self.vars.append(item)

        self.view.window().show_quick_panel(self.vars, self.write)

    def write(self, index):
        if index == -1: #escaped
            return
        name = self.vars[index][0]
        parser = Parser(self.getContent())
        for variable in parser.getClassVariables():
            if name == variable.getName():
                if 'getter' == self.what:
                    # code = self.generateGetterFunction(parser, variable)
                    self.view.run_command('php_generate_getters', {'name': name})
                elif 'setter' == self.what:
                    self.view.run_command('php_generate_setters', {'name': name})
                else:
                    self.view.run_command('php_generate_getters_setters', {'name': name})
                # self.writeAtEnd(self.edit, code)

class PhpGenerateGetterForCommand(PhpGenerateFor):
    what = 'getter'

class PhpGenerateSetterForCommand(PhpGenerateFor):
    what = 'setter'

class PhpGenerateGetterSetterForCommand(PhpGenerateFor):
    what = 'getter-setter'

class PhpGenerateGettersCommand(Base):
    def run(self, edit, **args):
        if not 'name' in args:
            args['name'] = None

        parser = Parser(self.getContent())
        code = ''
        for variable in parser.getClassVariables():
            if args['name'] is not None and variable.getName() != args['name']:
                continue

            code += self.generateGetterFunction(parser, variable)

        self.writeAtEnd(edit, code)

class PhpGenerateSettersCommand(Base):
    def run(self, edit, **args):
        if not 'name' in args:
            args['name'] = None

        parser = Parser(self.getContent())
        code = ''
        for variable in parser.getClassVariables():
            if args['name'] is not None and variable.getName() != args['name']:
                continue

            code += self.generateSetterFunction(parser, variable)

        self.writeAtEnd(edit, code)

class PhpGenerateGettersSettersCommand(Base):
    def run(self, edit, **args):
        if not 'name' in args:
            args['name'] = None

        settings = prefs()

        parser = Parser(self.getContent())
        code = ''
        for variable in parser.getClassVariables():
            if args['name'] is not None and variable.getName() != args['name']:
                continue

            if settings.get("setter_before_getter", False):
                code += self.generateSetterFunction(parser, variable)
                code += self.generateGetterFunction(parser, variable)
            else:
                code += self.generateGetterFunction(parser, variable)
                code += self.generateSetterFunction(parser, variable)

        self.writeAtEnd(edit, code)


class PhpGenerateGettersSetterUnavailable(Base):
    def run(self, edit):
        pass

    def is_enabled(self):
        return False

    def is_visible(self):
        return not self.isPhpSyntax()

    def description(self):
        return "Only available for PHP syntax buffers"

class PSR2:
    name = "PSR2"
    style = "camelCase"

  getter = """
    /**
     * @return %(type)s
     */
    public function %(getterPrefix)s%(normalizedName)s()
    {
        return $this->%(name)s;
    }
"""

  setter = """
    /**
     * @param %(type)s $%(name)s
     *
     * @return self
     */
    public function %(setterPrefix)s%(normalizedName)s(%(typeHint)s $%(name)s)
    {
        $this->%(name)s = $%(name)s;

        return $this;
    }
"""

class camelCase:
    name = "camelCase"
    style = 'camelCase'
    getter = """
    /**
     * Gets the %(description)s.
     *
     * @return %(type)s
     */
    public function get%(normalizedName)s()
    {
        return $this->%(name)s;
    }
"""

    setter = """
    /**
     * Sets the %(description)s.
     *
     * @param %(type)s $%(name)s the %(humanName)s
     *
     * @return self
     */
    %(visibility)s function %(visibilityPrefix)sset%(normalizedName)s(%(typeHint)s $%(param)s)
    {
        $this->%(name)s = $%(param)s;

        return $this;
    }
"""

class camelCaseFluent(camelCase):
    name = "camelCaseFluent"
    style = 'camelCase'
    setter = """
    /**
     * Sets the %(description)s.
     *
     * @param %(type)s $%(name)s the %(humanName)s
     *
     * @return self
     */
    %(visibility)s function %(visibilityPrefix)sset%(normalizedName)s(%(typeHint)s $%(param)s)
    {
        $this->%(name)s = $%(param)s;

        return $this;
    }
"""

class snakeCase:
    name = "snakeCase"
    style = 'snakeCase'
    getter = """
    /**
     * Gets the %(description)s.
     *
     * @return %(type)s
     */
    public function get_%(normalizedName)s()
    {
        return $this->%(name)s;
    }
"""
    setter = """
    /**
     * Sets the %(description)s.
     *
     * @param %(type)s $%(name)s the %(name)s
     *
     * @return self
     */
    %(visibility)s function %(visibilityPrefix)sset_%(normalizedName)s(%(typeHint)s $%(param)s)
    {
        $this->%(name)s = $%(param)s;

        return $this;
    }
"""

class snakeCaseFluent(snakeCase):
    name = "snakeCaseFluent"
    style = 'snakeCase'
    setter = """
    /**
     * Sets the %(description)s.
     *
     * @param %(type)s $%(name)s the %(name)s
     *
     * @return self
     */
    %(visibility)s function %(visibilityPrefix)sset_%(normalizedName)s(%(typeHint)s $%(param)s)
    {
        $this->%(name)s = $%(param)s;

        return $this;
    }
"""

templateManager = TemplateManager()

def plugin_loaded():
    templateManager.register(PSR2())
    templateManager.register(camelCase())
    templateManager.register(camelCaseFluent())
    templateManager.register(snakeCase())
    templateManager.register(snakeCaseFluent())

    for template in prefs().get('user_templates', []):
        templateManager.register(eval(template+'()'))