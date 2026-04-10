#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 Tom Haynes <loghyr@gmail.com>
# SPDX-License-Identifier: Apache-2.0
#
# xdr_parser.py - XDR parser and code generator
#
# A clean, hand-written recursive descent parser for XDR (RFC 4506)
# with RPC extensions (RFC 5531). Generates Python or C code.
#
# This is 100% original code with no dependencies on PLY or any
# GPL/LGPL-licensed libraries.

import sys
import os
import argparse
import time
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import List, Optional, Union


##########################################################################
#                          Token Types                                   #
##########################################################################

class TokenType(Enum):
    # Keywords
    BOOL = auto()
    CASE = auto()
    CONST = auto()
    DEFAULT = auto()
    DOUBLE = auto()
    QUADRUPLE = auto()
    ENUM = auto()
    FLOAT = auto()
    HYPER = auto()
    INT = auto()
    LONG = auto()
    OPAQUE = auto()
    STRING = auto()
    STRUCT = auto()
    SWITCH = auto()
    TYPEDEF = auto()
    UNION = auto()
    UNSIGNED = auto()
    VOID = auto()
    PROGRAM = auto()
    VERSION = auto()
    # Literals
    IDENT = auto()
    CONST_DEC = auto()
    CONST_HEX = auto()
    CONST_OCT = auto()
    # Symbols
    LPAREN = auto()
    RPAREN = auto()
    LBRACKET = auto()
    RBRACKET = auto()
    LBRACE = auto()
    RBRACE = auto()
    SEMI = auto()
    COLON = auto()
    LT = auto()
    GT = auto()
    STAR = auto()
    EQUALS = auto()
    COMMA = auto()
    # Special
    PASSTHROUGH = auto()
    EOF = auto()


KEYWORDS = {
    'bool': TokenType.BOOL,
    'case': TokenType.CASE,
    'const': TokenType.CONST,
    'default': TokenType.DEFAULT,
    'double': TokenType.DOUBLE,
    'quadruple': TokenType.QUADRUPLE,
    'enum': TokenType.ENUM,
    'float': TokenType.FLOAT,
    'hyper': TokenType.HYPER,
    'int': TokenType.INT,
    'long': TokenType.LONG,
    'opaque': TokenType.OPAQUE,
    'string': TokenType.STRING,
    'struct': TokenType.STRUCT,
    'switch': TokenType.SWITCH,
    'typedef': TokenType.TYPEDEF,
    'union': TokenType.UNION,
    'unsigned': TokenType.UNSIGNED,
    'void': TokenType.VOID,
    'program': TokenType.PROGRAM,
    'version': TokenType.VERSION,
}

SYMBOLS = {
    '(': TokenType.LPAREN,
    ')': TokenType.RPAREN,
    '[': TokenType.LBRACKET,
    ']': TokenType.RBRACKET,
    '{': TokenType.LBRACE,
    '}': TokenType.RBRACE,
    ';': TokenType.SEMI,
    ':': TokenType.COLON,
    '<': TokenType.LT,
    '>': TokenType.GT,
    '*': TokenType.STAR,
    '=': TokenType.EQUALS,
    ',': TokenType.COMMA,
}


@dataclass
class Token:
    type: TokenType
    value: str
    line: int
    col: int


##########################################################################
#                              Lexer                                     #
##########################################################################

class LexerError(Exception):
    def __init__(self, msg, line, col):
        super().__init__(f"{msg} at line {line}, col {col}")
        self.line = line
        self.col = col


class Lexer:
    def __init__(self, text: str):
        self.text = text
        self.pos = 0
        self.line = 1
        self.col = 1
        self.tokens: List[Token] = []
        self._tokenize()

    def _peek(self) -> str:
        if self.pos < len(self.text):
            return self.text[self.pos]
        return '\0'

    def _advance(self) -> str:
        ch = self.text[self.pos]
        self.pos += 1
        if ch == '\n':
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        return ch

    def _skip_whitespace(self):
        while self.pos < len(self.text) and self.text[self.pos] in ' \t\r\n':
            self._advance()

    def _skip_block_comment(self):
        # Already consumed '/*'
        while self.pos < len(self.text) - 1:
            if self.text[self.pos] == '*' and self.text[self.pos + 1] == '/':
                self._advance()  # *
                self._advance()  # /
                return
            self._advance()
        if self.pos < len(self.text):
            self._advance()
        raise LexerError("Unterminated block comment", self.line, self.col)

    def _skip_preprocessor_line(self):
        # Skip entire line starting with #
        while self.pos < len(self.text) and self.text[self.pos] != '\n':
            self._advance()

    def _read_passthrough_line(self) -> str:
        # Already consumed '%', read rest of line
        start = self.pos
        while self.pos < len(self.text) and self.text[self.pos] != '\n':
            self._advance()
        return self.text[start:self.pos]

    def _read_identifier(self) -> str:
        start = self.pos
        while self.pos < len(self.text) and (self.text[self.pos].isalnum() or self.text[self.pos] == '_'):
            self._advance()
        return self.text[start:self.pos]

    def _read_number(self) -> Token:
        line, col = self.line, self.col
        start = self.pos
        # Handle negative
        if self._peek() == '-':
            self._advance()
        if self.pos >= len(self.text) or not self.text[self.pos].isdigit():
            raise LexerError("Expected digit after '-'", line, col)
        if self.text[self.pos] == '0' and self.pos + 1 < len(self.text):
            next_ch = self.text[self.pos + 1]
            if next_ch in ('x', 'X'):
                # Hex
                self._advance()  # 0
                self._advance()  # x
                while self.pos < len(self.text) and self.text[self.pos] in '0123456789abcdefABCDEF':
                    self._advance()
                return Token(TokenType.CONST_HEX, self.text[start:self.pos], line, col)
            elif next_ch in '01234567':
                # Octal
                self._advance()  # 0
                while self.pos < len(self.text) and self.text[self.pos] in '01234567':
                    self._advance()
                return Token(TokenType.CONST_OCT, self.text[start:self.pos], line, col)
        # Decimal
        while self.pos < len(self.text) and self.text[self.pos].isdigit():
            self._advance()
        return Token(TokenType.CONST_DEC, self.text[start:self.pos], line, col)

    def _tokenize(self):
        while self.pos < len(self.text):
            # Skip whitespace
            if self.text[self.pos] in ' \t\r\n':
                self._skip_whitespace()
                continue

            line, col = self.line, self.col

            # Block comment
            if self.pos + 1 < len(self.text) and self.text[self.pos:self.pos+2] == '/*':
                self._advance()  # /
                self._advance()  # *
                self._skip_block_comment()
                continue

            # Preprocessor directive - skip entire line
            if self.text[self.pos] == '#':
                self._skip_preprocessor_line()
                continue

            # Passthrough line
            if self.text[self.pos] == '%':
                self._advance()  # %
                text = self._read_passthrough_line()
                self.tokens.append(Token(TokenType.PASSTHROUGH, text, line, col))
                continue

            # Identifier or keyword
            if self.text[self.pos].isalpha():
                ident = self._read_identifier()
                tt = KEYWORDS.get(ident, TokenType.IDENT)
                self.tokens.append(Token(tt, ident, line, col))
                continue

            # Number
            if self.text[self.pos].isdigit() or (
                self.text[self.pos] == '-' and self.pos + 1 < len(self.text) and self.text[self.pos + 1].isdigit()
            ):
                self.tokens.append(self._read_number())
                continue

            # Symbol
            ch = self.text[self.pos]
            if ch in SYMBOLS:
                self._advance()
                self.tokens.append(Token(SYMBOLS[ch], ch, line, col))
                continue

            raise LexerError(f"Unexpected character {ch!r}", line, col)

        self.tokens.append(Token(TokenType.EOF, '', self.line, self.col))


##########################################################################
#                           AST Nodes                                    #
##########################################################################

@dataclass
class TypeSpec:
    """Base for type specifiers."""
    line: int = 0
    col: int = 0

@dataclass
class BasicType(TypeSpec):
    name: str = ''  # int, hyper, float, double, quadruple, bool

@dataclass
class UnsignedType(TypeSpec):
    name: str = ''  # uint, uhyper

@dataclass
class IdentifierType(TypeSpec):
    name: str = ''

@dataclass
class EnumConstant:
    name: str = ''
    value: str = ''
    line: int = 0

@dataclass
class InlineEnumType(TypeSpec):
    body: List[EnumConstant] = field(default_factory=list)

@dataclass
class InlineStructType(TypeSpec):
    body: list = field(default_factory=list)  # List[Declaration]

@dataclass
class InlineUnionType(TypeSpec):
    discriminant: 'Declaration' = None
    cases: list = field(default_factory=list)  # List[CaseSpec]
    default_arm: Optional['Declaration'] = None

# Declarations
@dataclass
class Declaration:
    line: int = 0
    col: int = 0

@dataclass
class SimpleDecl(Declaration):
    type_spec: TypeSpec = None
    name: str = ''

@dataclass
class FixedArrayDecl(Declaration):
    type_spec: TypeSpec = None
    name: str = ''
    size: str = ''

@dataclass
class VarArrayDecl(Declaration):
    type_spec: TypeSpec = None
    name: str = ''
    max_size: Optional[str] = None

@dataclass
class OpaqueFixedDecl(Declaration):
    name: str = ''
    size: str = ''

@dataclass
class OpaqueVarDecl(Declaration):
    name: str = ''
    max_size: Optional[str] = None

@dataclass
class StringDecl(Declaration):
    name: str = ''
    max_size: Optional[str] = None

@dataclass
class PointerDecl(Declaration):
    type_spec: TypeSpec = None
    name: str = ''

@dataclass
class VoidDecl(Declaration):
    pass

# Case spec for unions
@dataclass
class CaseSpec:
    case_values: List[str] = field(default_factory=list)
    declaration: Declaration = None

# Top-level definitions
@dataclass
class Definition:
    line: int = 0
    col: int = 0

@dataclass
class ConstDef(Definition):
    name: str = ''
    value: str = ''

@dataclass
class EnumDef(Definition):
    name: str = ''
    body: List[EnumConstant] = field(default_factory=list)

@dataclass
class StructDef(Definition):
    name: str = ''
    body: List[Declaration] = field(default_factory=list)

@dataclass
class UnionDef(Definition):
    name: str = ''
    discriminant: Declaration = None
    cases: List[CaseSpec] = field(default_factory=list)
    default_arm: Optional[Declaration] = None

@dataclass
class TypeDef(Definition):
    declaration: Declaration = None

@dataclass
class ProcedureDef:
    name: str = ''
    proc_number: str = ''
    return_type: TypeSpec = None
    arg_types: List[TypeSpec] = field(default_factory=list)
    line: int = 0

@dataclass
class VersionDef:
    name: str = ''
    version_number: str = ''
    procedures: List[ProcedureDef] = field(default_factory=list)
    line: int = 0

@dataclass
class ProgramDef(Definition):
    name: str = ''
    program_number: str = ''
    versions: List[VersionDef] = field(default_factory=list)

@dataclass
class PassthroughLine(Definition):
    text: str = ''

@dataclass
class Specification:
    definitions: List[Definition] = field(default_factory=list)


##########################################################################
#                             Parser                                     #
##########################################################################

class ParseError(Exception):
    def __init__(self, msg, token=None):
        if token:
            super().__init__(f"{msg} at line {token.line}, col {token.col}")
        else:
            super().__init__(msg)


class Parser:
    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.pos = 0

    def _current(self) -> Token:
        return self.tokens[self.pos]

    def _peek(self, offset=0) -> Token:
        idx = self.pos + offset
        if idx < len(self.tokens):
            return self.tokens[idx]
        return self.tokens[-1]  # EOF

    def _advance(self) -> Token:
        tok = self.tokens[self.pos]
        if self.pos < len(self.tokens) - 1:
            self.pos += 1
        return tok

    def _expect(self, tt: TokenType) -> Token:
        tok = self._current()
        if tok.type != tt:
            raise ParseError(f"Expected {tt.name}, got {tok.type.name} ({tok.value!r})", tok)
        return self._advance()

    def _skip_passthrough(self) -> List[PassthroughLine]:
        lines = []
        while self._current().type == TokenType.PASSTHROUGH:
            tok = self._advance()
            lines.append(PassthroughLine(line=tok.line, col=tok.col, text=tok.value))
        return lines

    def parse(self) -> Specification:
        spec = Specification()
        while self._current().type != TokenType.EOF:
            passlines = self._skip_passthrough()
            spec.definitions.extend(passlines)
            if self._current().type == TokenType.EOF:
                break
            defn = self._parse_definition()
            if defn is not None:
                spec.definitions.append(defn)
        return spec

    def _parse_definition(self) -> Optional[Definition]:
        tok = self._current()
        if tok.type == TokenType.CONST:
            return self._parse_const_def()
        elif tok.type == TokenType.TYPEDEF:
            return self._parse_typedef()
        elif tok.type == TokenType.ENUM:
            return self._parse_enum_def()
        elif tok.type == TokenType.STRUCT:
            return self._parse_struct_def()
        elif tok.type == TokenType.UNION:
            return self._parse_union_def()
        elif tok.type == TokenType.PROGRAM:
            return self._parse_program_def()
        elif tok.type == TokenType.PASSTHROUGH:
            tok = self._advance()
            return PassthroughLine(line=tok.line, col=tok.col, text=tok.value)
        else:
            raise ParseError(f"Unexpected token {tok.value!r}", tok)

    def _parse_const_def(self) -> ConstDef:
        tok = self._expect(TokenType.CONST)
        name_tok = self._expect(TokenType.IDENT)
        self._expect(TokenType.EQUALS)
        value = self._parse_value()
        self._expect(TokenType.SEMI)
        return ConstDef(line=tok.line, col=tok.col, name=name_tok.value, value=value)

    def _parse_value(self) -> str:
        tok = self._current()
        if tok.type in (TokenType.CONST_DEC, TokenType.CONST_HEX, TokenType.CONST_OCT):
            self._advance()
            return tok.value
        elif tok.type == TokenType.IDENT:
            self._advance()
            return tok.value
        else:
            raise ParseError(f"Expected value, got {tok.type.name} ({tok.value!r})", tok)

    def _parse_optional_value(self) -> Optional[str]:
        if self._current().type == TokenType.GT:
            return None
        return self._parse_value()

    def _parse_typedef(self) -> Definition:
        tok = self._expect(TokenType.TYPEDEF)
        decl = self._parse_declaration()
        self._expect(TokenType.SEMI)
        # If it's an inline enum/struct/union with a name, promote to named def
        if isinstance(decl, (SimpleDecl, FixedArrayDecl, VarArrayDecl)):
            ts = decl.type_spec if hasattr(decl, 'type_spec') else None
            if isinstance(ts, InlineEnumType):
                name = decl.name
                return EnumDef(line=tok.line, col=tok.col, name=name, body=ts.body)
            elif isinstance(ts, InlineStructType):
                name = decl.name
                return StructDef(line=tok.line, col=tok.col, name=name, body=ts.body)
            elif isinstance(ts, InlineUnionType):
                name = decl.name
                return UnionDef(line=tok.line, col=tok.col, name=name,
                               discriminant=ts.discriminant, cases=ts.cases,
                               default_arm=ts.default_arm)
        return TypeDef(line=tok.line, col=tok.col, declaration=decl)

    def _parse_enum_def(self) -> EnumDef:
        tok = self._expect(TokenType.ENUM)
        name_tok = self._expect(TokenType.IDENT)
        body = self._parse_enum_body()
        self._expect(TokenType.SEMI)
        return EnumDef(line=tok.line, col=tok.col, name=name_tok.value, body=body)

    def _parse_enum_body(self) -> List[EnumConstant]:
        self._expect(TokenType.LBRACE)
        members = []
        self._skip_passthrough()
        members.append(self._parse_enum_constant())
        while self._current().type == TokenType.COMMA:
            self._advance()
            self._skip_passthrough()
            if self._current().type == TokenType.RBRACE:
                break  # trailing comma
            members.append(self._parse_enum_constant())
            self._skip_passthrough()
        self._skip_passthrough()
        self._expect(TokenType.RBRACE)
        return members

    def _parse_enum_constant(self) -> EnumConstant:
        name_tok = self._expect(TokenType.IDENT)
        self._expect(TokenType.EQUALS)
        value = self._parse_value()
        return EnumConstant(name=name_tok.value, value=value, line=name_tok.line)

    def _parse_struct_def(self) -> StructDef:
        tok = self._expect(TokenType.STRUCT)
        name_tok = self._expect(TokenType.IDENT)
        # Check: is next token '{' (struct body) or identifier (struct as type prefix)?
        if self._current().type != TokenType.LBRACE:
            raise ParseError(f"Expected '{{' for struct body, got {self._current().value!r}", self._current())
        body = self._parse_struct_body()
        self._expect(TokenType.SEMI)
        return StructDef(line=tok.line, col=tok.col, name=name_tok.value, body=body)

    def _parse_struct_body(self) -> List[Declaration]:
        self._expect(TokenType.LBRACE)
        members = []
        while self._current().type != TokenType.RBRACE:
            self._skip_passthrough()
            if self._current().type == TokenType.RBRACE:
                break
            decl = self._parse_declaration()
            self._expect(TokenType.SEMI)
            members.append(decl)
        self._expect(TokenType.RBRACE)
        return members

    def _parse_union_def(self) -> UnionDef:
        tok = self._expect(TokenType.UNION)
        name_tok = self._expect(TokenType.IDENT)
        discrim, cases, default_arm = self._parse_union_body()
        self._expect(TokenType.SEMI)
        return UnionDef(line=tok.line, col=tok.col, name=name_tok.value,
                       discriminant=discrim, cases=cases, default_arm=default_arm)

    def _parse_union_body(self):
        self._expect(TokenType.SWITCH)
        self._expect(TokenType.LPAREN)
        discrim = self._parse_declaration()
        self._expect(TokenType.RPAREN)
        self._expect(TokenType.LBRACE)
        cases = []
        default_arm = None
        while self._current().type != TokenType.RBRACE:
            self._skip_passthrough()
            if self._current().type == TokenType.DEFAULT:
                self._advance()
                self._expect(TokenType.COLON)
                default_arm = self._parse_declaration()
                self._expect(TokenType.SEMI)
                self._skip_passthrough()
                break
            elif self._current().type == TokenType.CASE:
                case_values = []
                while self._current().type == TokenType.CASE:
                    self._advance()
                    val = self._parse_value()
                    self._expect(TokenType.COLON)
                    case_values.append(val)
                decl = self._parse_declaration()
                self._expect(TokenType.SEMI)
                cases.append(CaseSpec(case_values=case_values, declaration=decl))
            elif self._current().type == TokenType.RBRACE:
                break
            else:
                raise ParseError(f"Expected 'case' or 'default', got {self._current().value!r}", self._current())
        self._expect(TokenType.RBRACE)
        return discrim, cases, default_arm

    def _parse_declaration(self) -> Declaration:
        tok = self._current()

        # void
        if tok.type == TokenType.VOID:
            self._advance()
            return VoidDecl(line=tok.line, col=tok.col)

        # opaque ...
        if tok.type == TokenType.OPAQUE:
            self._advance()
            # opaque * ID (pointer) or opaque ID [size] or opaque ID <max>
            if self._current().type == TokenType.STAR:
                self._advance()
                name_tok = self._expect(TokenType.IDENT)
                return PointerDecl(line=tok.line, col=tok.col,
                                   type_spec=BasicType(line=tok.line, col=tok.col, name='opaque'),
                                   name=name_tok.value)
            name_tok = self._expect(TokenType.IDENT)
            if self._current().type == TokenType.LBRACKET:
                self._advance()
                size = self._parse_value()
                self._expect(TokenType.RBRACKET)
                return OpaqueFixedDecl(line=tok.line, col=tok.col, name=name_tok.value, size=size)
            elif self._current().type == TokenType.LT:
                self._advance()
                max_size = self._parse_optional_value()
                self._expect(TokenType.GT)
                return OpaqueVarDecl(line=tok.line, col=tok.col, name=name_tok.value, max_size=max_size)
            else:
                raise ParseError("Expected '[' or '<' after opaque identifier", self._current())

        # string ...
        if tok.type == TokenType.STRING:
            self._advance()
            # string * ID (pointer) or string ID <max>
            if self._current().type == TokenType.STAR:
                self._advance()
                name_tok = self._expect(TokenType.IDENT)
                return PointerDecl(line=tok.line, col=tok.col,
                                   type_spec=BasicType(line=tok.line, col=tok.col, name='string'),
                                   name=name_tok.value)
            name_tok = self._expect(TokenType.IDENT)
            self._expect(TokenType.LT)
            max_size = self._parse_optional_value()
            self._expect(TokenType.GT)
            return StringDecl(line=tok.line, col=tok.col, name=name_tok.value, max_size=max_size)

        # type_specifier ...
        ts = self._parse_type_specifier()

        # type_specifier * ID  (pointer)
        if self._current().type == TokenType.STAR:
            self._advance()
            name_tok = self._expect(TokenType.IDENT)
            return PointerDecl(line=tok.line, col=tok.col, type_spec=ts, name=name_tok.value)

        # type_specifier ID ...
        name_tok = self._expect(TokenType.IDENT)

        # type_specifier ID [ size ]
        if self._current().type == TokenType.LBRACKET:
            self._advance()
            size = self._parse_value()
            self._expect(TokenType.RBRACKET)
            return FixedArrayDecl(line=tok.line, col=tok.col, type_spec=ts,
                                 name=name_tok.value, size=size)

        # type_specifier ID < max >
        if self._current().type == TokenType.LT:
            self._advance()
            max_size = self._parse_optional_value()
            self._expect(TokenType.GT)
            return VarArrayDecl(line=tok.line, col=tok.col, type_spec=ts,
                               name=name_tok.value, max_size=max_size)

        # type_specifier ID
        return SimpleDecl(line=tok.line, col=tok.col, type_spec=ts, name=name_tok.value)

    def _parse_type_specifier(self) -> TypeSpec:
        tok = self._current()

        # unsigned [int|hyper|long]
        if tok.type == TokenType.UNSIGNED:
            self._advance()
            if self._current().type == TokenType.INT:
                self._advance()
                return UnsignedType(line=tok.line, col=tok.col, name='uint')
            elif self._current().type == TokenType.HYPER:
                self._advance()
                return UnsignedType(line=tok.line, col=tok.col, name='uhyper')
            elif self._current().type == TokenType.LONG:
                self._advance()
                return UnsignedType(line=tok.line, col=tok.col, name='uint')
            else:
                # bare "unsigned" means unsigned int
                return UnsignedType(line=tok.line, col=tok.col, name='uint')

        # long -> int
        if tok.type == TokenType.LONG:
            self._advance()
            return BasicType(line=tok.line, col=tok.col, name='int')

        # basic types
        if tok.type in (TokenType.INT, TokenType.HYPER, TokenType.FLOAT,
                        TokenType.DOUBLE, TokenType.QUADRUPLE, TokenType.BOOL):
            self._advance()
            return BasicType(line=tok.line, col=tok.col, name=tok.value)

        # enum inline
        if tok.type == TokenType.ENUM:
            self._advance()
            body = self._parse_enum_body()
            return InlineEnumType(line=tok.line, col=tok.col, body=body)

        # struct - inline body, named inline, or type prefix
        if tok.type == TokenType.STRUCT:
            self._advance()
            if self._current().type == TokenType.LBRACE:
                body = self._parse_struct_body()
                return InlineStructType(line=tok.line, col=tok.col, body=body)
            else:
                # "struct IDENT" - could be type prefix or named inline struct
                name_tok = self._expect(TokenType.IDENT)
                if self._current().type == TokenType.LBRACE:
                    # "struct foo { ... }" -- inline named struct definition
                    body = self._parse_struct_body()
                    return InlineStructType(line=tok.line, col=tok.col, body=body)
                else:
                    # "struct foo" as type prefix
                    return IdentifierType(line=tok.line, col=tok.col, name=name_tok.value)

        # union inline
        if tok.type == TokenType.UNION:
            self._advance()
            discrim, cases, default_arm = self._parse_union_body()
            return InlineUnionType(line=tok.line, col=tok.col,
                                  discriminant=discrim, cases=cases,
                                  default_arm=default_arm)

        # string and opaque as type specifiers (e.g., in procedure args)
        if tok.type == TokenType.STRING:
            self._advance()
            return BasicType(line=tok.line, col=tok.col, name='string')

        if tok.type == TokenType.OPAQUE:
            self._advance()
            return BasicType(line=tok.line, col=tok.col, name='opaque')

        # identifier
        if tok.type == TokenType.IDENT:
            self._advance()
            return IdentifierType(line=tok.line, col=tok.col, name=tok.value)

        raise ParseError(f"Expected type specifier, got {tok.type.name} ({tok.value!r})", tok)

    def _parse_program_def(self) -> ProgramDef:
        tok = self._expect(TokenType.PROGRAM)
        name_tok = self._expect(TokenType.IDENT)
        self._expect(TokenType.LBRACE)
        versions = []
        while self._current().type != TokenType.RBRACE:
            self._skip_passthrough()
            if self._current().type == TokenType.RBRACE:
                break
            versions.append(self._parse_version_def())
        self._expect(TokenType.RBRACE)
        self._expect(TokenType.EQUALS)
        prog_num = self._parse_value()
        self._expect(TokenType.SEMI)
        return ProgramDef(line=tok.line, col=tok.col, name=name_tok.value,
                         program_number=prog_num, versions=versions)

    def _parse_version_def(self) -> VersionDef:
        tok = self._expect(TokenType.VERSION)
        name_tok = self._expect(TokenType.IDENT)
        self._expect(TokenType.LBRACE)
        procs = []
        while self._current().type != TokenType.RBRACE:
            self._skip_passthrough()
            if self._current().type == TokenType.RBRACE:
                break
            procs.append(self._parse_procedure_def())
        self._expect(TokenType.RBRACE)
        self._expect(TokenType.EQUALS)
        ver_num = self._parse_value()
        self._expect(TokenType.SEMI)
        return VersionDef(name=name_tok.value, version_number=ver_num,
                         procedures=procs, line=tok.line)

    def _parse_procedure_def(self) -> ProcedureDef:
        tok = self._current()
        # Return type
        if self._current().type == TokenType.VOID:
            ret_type = BasicType(line=tok.line, col=tok.col, name='void')
            self._advance()
        else:
            ret_type = self._parse_type_specifier()
        name_tok = self._expect(TokenType.IDENT)
        self._expect(TokenType.LPAREN)
        arg_types = []
        if self._current().type == TokenType.VOID:
            self._advance()
        else:
            arg_types.append(self._parse_type_specifier())
            while self._current().type == TokenType.COMMA:
                self._advance()
                arg_types.append(self._parse_type_specifier())
        self._expect(TokenType.RPAREN)
        self._expect(TokenType.EQUALS)
        proc_num = self._parse_value()
        self._expect(TokenType.SEMI)
        return ProcedureDef(name=name_tok.value, proc_number=proc_num,
                           return_type=ret_type, arg_types=arg_types, line=tok.line)


##########################################################################
#                      Python Code Generator                             #
##########################################################################

INDENT = '    '
INDENT2 = INDENT * 2
INDENT3 = INDENT * 3

import keyword as _keyword

# Python keywords that can appear as XDR field names
_PYTHON_KEYWORDS = set(_keyword.kwlist)


def _py_name(name: str) -> str:
    """Escape Python keywords used as identifiers by appending underscore."""
    if name in _PYTHON_KEYWORDS:
        return name + '_'
    return name

# Maps XDR type names to xdrlib pack/unpack method names
KNOWN_BASICS = {
    'int': 'pack_int',
    'uint': 'pack_uint',
    'unsigned': 'pack_uint',
    'hyper': 'pack_hyper',
    'uhyper': 'pack_uhyper',
    'float': 'pack_float',
    'double': 'pack_double',
    'quadruple': 'pack_double',
    'bool': 'pack_bool',
    'opaque': 'pack_opaque',
    'string': 'pack_string',
}


def _fullname(value: str) -> str:
    """Prepend 'const.' to identifier references."""
    if value and (value[0].isdigit() or value[0] == '-'):
        return value
    return 'const.' + value


def _type_name(ts: TypeSpec) -> str:
    """Get the type name string from a TypeSpec."""
    if isinstance(ts, BasicType):
        return ts.name
    elif isinstance(ts, UnsignedType):
        return ts.name
    elif isinstance(ts, IdentifierType):
        return ts.name
    return ''


def _raw_decl_name(decl: Declaration) -> Optional[str]:
    """Get the raw field name from a declaration, or None for void."""
    if isinstance(decl, VoidDecl):
        return None
    if hasattr(decl, 'name'):
        return decl.name
    return None


def _decl_name(decl: Declaration) -> Optional[str]:
    """Get the Python-safe field name from a declaration, or None for void."""
    name = _raw_decl_name(decl)
    if name is not None:
        return _py_name(name)
    return name


def _decl_type_name(decl: Declaration) -> str:
    """Get the type name from a declaration."""
    if isinstance(decl, (SimpleDecl, FixedArrayDecl, VarArrayDecl, PointerDecl)):
        return _type_name(decl.type_spec)
    elif isinstance(decl, (OpaqueFixedDecl, OpaqueVarDecl)):
        return 'opaque'
    elif isinstance(decl, StringDecl):
        return 'string'
    elif isinstance(decl, VoidDecl):
        return 'void'
    return ''


class PythonCodeGenerator:
    def __init__(self, spec: Specification, prefix: str, use_filters: bool = True,
                 allow_attr_passthrough: bool = True):
        self.spec = spec
        self.prefix = prefix
        self.use_filters = use_filters
        self.allow_attr_passthrough = allow_attr_passthrough
        # Build name dict for type lookups
        self.name_dict = {}
        for defn in spec.definitions:
            if isinstance(defn, ConstDef):
                self.name_dict[defn.name] = defn
            elif isinstance(defn, EnumDef):
                self.name_dict[defn.name] = defn
                for ec in defn.body:
                    self.name_dict[ec.name] = ConstDef(name=ec.name, value=ec.value,
                                                       line=ec.line)
            elif isinstance(defn, StructDef):
                self.name_dict[defn.name] = defn
            elif isinstance(defn, UnionDef):
                self.name_dict[defn.name] = defn
            elif isinstance(defn, TypeDef):
                name = _decl_name(defn.declaration)
                if name:
                    self.name_dict[name] = defn
            elif isinstance(defn, ProgramDef):
                self.name_dict[defn.name] = defn
                for ver in defn.versions:
                    self.name_dict[ver.name] = ver
                    for proc in ver.procedures:
                        self.name_dict[proc.name] = proc

    def generate(self, output_dir: str):
        const_file = os.path.join(output_dir, self.prefix + '_const.py')
        type_file = os.path.join(output_dir, self.prefix + '_type.py')
        pack_file = os.path.join(output_dir, self.prefix + '_pack.py')

        const_lines = []
        type_lines = []
        pack_lines = []
        unpack_lines = []

        comment = "# DO NOT EDIT - generated by xdr_parser.py from %s\n" \
                  "# Apply changes to %s instead.\n" % (
            self.prefix + '.x', self.prefix + '.x')

        # const header
        const_lines.append(comment)

        # type header
        type_lines.append(comment)
        type_lines.append("import sys,os\nfrom . import %s_const as const\n" % self.prefix)

        # pack header
        pack_lines.append(comment)
        pack_lines.append("import sys,os\n")
        pack_lines.append("from . import %s_const as const\n" % self.prefix)
        pack_lines.append("from . import %s_type as types\n\n" % self.prefix)
        pack_lines.append("try:\n")
        pack_lines.append("    import xdrlib3 as xdrlib\n")
        pack_lines.append("    from xdrlib3 import Error as XDRError\n")
        pack_lines.append("except:\n")
        pack_lines.append("    import xdrlib as xdrlib\n")
        pack_lines.append("    from xdrlib import Error as XDRError\n\n")
        pack_lines.append("class nullclass(object):\n    pass\n\n")

        # Packer class
        class_name = self.prefix.upper()
        pack_lines.append("class %sPacker(xdrlib.Packer):\n" % class_name)
        pack_lines.append("%sdef __init__(self, check_enum=True, check_array=True):\n" % INDENT)
        pack_lines.append("%sxdrlib.Packer.__init__(self)\n" % INDENT2)
        pack_lines.append("%sself.check_enum = check_enum\n" % INDENT2)
        pack_lines.append("%sself.check_array = check_array\n\n" % INDENT2)

        # Basic type aliases for packer
        for k, v in KNOWN_BASICS.items():
            pack_lines.append("%spack_%s = xdrlib.Packer.%s\n" % (INDENT, k, v))

        # Generate for each definition in order
        for defn in self.spec.definitions:
            c = self._gen_const(defn)
            if c:
                const_lines.append(c)
            t = self._gen_type(defn)
            if t:
                type_lines.append(t)
            p = self._gen_pack(defn)
            if p:
                pack_lines.append(p)
                pack_lines.append('\n')
            u = self._gen_unpack(defn)
            if u:
                unpack_lines.append(u)
                unpack_lines.append('\n')

        # Unpacker class
        pack_lines.append("\nclass %sUnpacker(xdrlib.Unpacker):\n" % class_name)
        pack_lines.append("%sdef __init__(self, data, check_enum=True, check_array=True):\n" % INDENT)
        pack_lines.append("%sxdrlib.Unpacker.__init__(self, data)\n" % INDENT2)
        pack_lines.append("%sself.check_enum = check_enum\n" % INDENT2)
        pack_lines.append("%sself.check_array = check_array\n\n" % INDENT2)

        # Basic type aliases for unpacker
        for k, v in KNOWN_BASICS.items():
            pack_lines.append("%sunpack_%s = xdrlib.Unpacker.un%s\n" % (INDENT, k, v))

        # Unpack methods
        pack_lines.extend(unpack_lines)

        with open(const_file, 'w') as f:
            f.write(''.join(const_lines))
        with open(type_file, 'w') as f:
            f.write(''.join(type_lines))
        with open(pack_file, 'w') as f:
            f.write(''.join(pack_lines))

    def _gen_const(self, defn) -> str:
        if isinstance(defn, ConstDef):
            return "%s = %s\n" % (defn.name, defn.value)
        elif isinstance(defn, EnumDef):
            out = ''
            # Individual enum constants
            for ec in defn.body:
                out += "%s = %s\n" % (ec.name, ec.value)
            # Enum reverse-map dict
            out += "%s = {\n" % defn.name
            for ec in defn.body:
                out += "%s%s : '%s',\n" % (INDENT, ec.value, ec.name)
            out += "}\n"
            return out
        elif isinstance(defn, ProgramDef):
            out = "%s = %s\n" % (defn.name, defn.program_number)
            for ver in defn.versions:
                out += "%s = %s\n" % (ver.name, ver.version_number)
                for proc in ver.procedures:
                    out += "%s = %s\n" % (proc.name, proc.proc_number)
            return out
        return ''

    def _gen_type(self, defn) -> str:
        if isinstance(defn, StructDef):
            return self._gen_struct_type(defn)
        elif isinstance(defn, UnionDef):
            return self._gen_union_type(defn)
        elif isinstance(defn, TypeDef):
            return self._gen_typedef_type(defn)
        return ''

    def _gen_struct_type(self, defn: StructDef) -> str:
        varlist = [d for d in defn.body if not isinstance(d, VoidDecl)]

        # XDR comment
        out = "class %s:\n" % defn.name
        comment = INDENT + '# '
        out += "%sXDR definition:\n" % comment
        out += "%sstruct %s {\n" % (comment, defn.name)
        for d in defn.body:
            out += "%s%s\n" % (comment + INDENT, self._xdr_decl_str(d))
        out += "%s};\n" % comment

        # __init__
        out += self._typeinit(varlist)
        out += "\n"

        # __getattr__ passthrough
        out += self._pass_through(varlist)

        # __repr__
        out += self._typerepr(defn.name, varlist)
        out += "\n"
        return out

    def _gen_union_type(self, defn: UnionDef) -> str:
        # Collect all vars (discriminant + case arms)
        varlist = []
        if not isinstance(defn.discriminant, VoidDecl):
            varlist.append(defn.discriminant)
        for cs in defn.cases:
            if not isinstance(cs.declaration, VoidDecl):
                varlist.append(cs.declaration)
        if defn.default_arm and not isinstance(defn.default_arm, VoidDecl):
            varlist.append(defn.default_arm)

        out = "class %s:\n" % defn.name
        comment = INDENT + '# '
        out += "%sXDR definition:\n" % comment
        discrim_name = _decl_name(defn.discriminant)
        discrim_type = _decl_type_name(defn.discriminant)
        out += "%sunion %s switch(%s %s) {\n" % (comment, defn.name, discrim_type, discrim_name or '')
        for cs in defn.cases:
            for cv in cs.case_values:
                out += "%scase %s:\n" % (comment + INDENT, cv)
            out += "%s%s\n" % (comment + INDENT + INDENT, self._xdr_decl_str(cs.declaration))
        if defn.default_arm is not None:
            out += "%sdefault:\n" % (comment + INDENT)
            out += "%s%s\n" % (comment + INDENT + INDENT, self._xdr_decl_str(defn.default_arm))
        out += "%s};\n" % comment

        out += self._typeinit(varlist)
        out += "\n"

        # switch property
        out += self._union_switch(defn)
        out += "\n"

        # __getattr__
        out += "%sdef __getattr__(self, attr):\n" % INDENT
        out += "%sreturn getattr(self.switch, attr)\n\n" % INDENT2

        out += self._typerepr(defn.name, varlist)
        out += "\n"
        return out

    def _union_switch(self, defn: UnionDef) -> str:
        """Generate the switch property for a union."""
        discrim_name = _decl_name(defn.discriminant)
        d = '{'
        for cs in defn.cases:
            arm_name = _decl_name(cs.declaration)
            for cv in cs.case_values:
                if arm_name is None:
                    d += "%s:None," % _fullname(cv)
                else:
                    d += "%s:s.%s," % (_fullname(cv), arm_name)
        d += '}'

        if defn.default_arm is not None:
            def_name = _decl_name(defn.default_arm)
            if def_name is None:
                get = ".get(s.%s, None)" % discrim_name
            else:
                get = ".get(s.%s, s.%s)" % (discrim_name, def_name)
        else:
            get = "[s.%s]" % discrim_name

        return "%sswitch = property(lambda s: %s%s)\n" % (INDENT, d, get)

    def _gen_typedef_type(self, defn: TypeDef) -> str:
        decl = defn.declaration
        name = _decl_name(decl)
        if not name:
            return ''

        # Simple typedef (no array) -> alias
        if isinstance(decl, SimpleDecl):
            ts = decl.type_spec
            type_name = _type_name(ts)
            resolved = self.name_dict.get(type_name)
            if resolved:
                if isinstance(resolved, (StructDef, UnionDef)):
                    return "%s = %s\n" % (name, type_name)
                elif isinstance(resolved, EnumDef):
                    return "%s = const.%s\n" % (name, type_name)
        return ''

    def _typeinit(self, varlist: list) -> str:
        names = [_decl_name(v) for v in varlist if _decl_name(v)]
        initargs = ''.join([", %s=None" % n for n in names])
        initvars = ''.join(["%sself.%s = %s\n" % (INDENT2, n, n) for n in names])
        return "%sdef __init__(self%s):\n%s" % (INDENT, initargs, initvars)

    def _typerepr(self, classname: str, varlist: list) -> str:
        names = [_decl_name(v) for v in varlist if _decl_name(v)]
        out = "%sdef __repr__(self):\n" % INDENT
        out += "%sout = []\n" % INDENT2
        for i, v in enumerate(varlist):
            n = _decl_name(v)
            if not n:
                continue
            special = self._repr_special(v)
            out += "%sif self.%s is not None:\n" % (INDENT2, n)
            out += "%sout += ['%s=%%s' %% %s]\n" % (INDENT3, n, special)
        out += "%sreturn '%s(%%s)' %% ', '.join(out)\n" % (INDENT2, classname)
        out += "%s__str__ = __repr__\n" % INDENT
        return out

    def _repr_special(self, decl) -> str:
        """For enum-typed fields, use the enum dict for repr."""
        type_name = _decl_type_name(decl)
        name = _decl_name(decl)
        resolved = self.name_dict.get(type_name)
        if isinstance(resolved, EnumDef):
            is_array = isinstance(decl, (FixedArrayDecl, VarArrayDecl))
            if is_array:
                return "','.join([const.%s.get(x, x) for x in self.%s])" % (resolved.name, name)
            return "const.%s.get(self.%s, self.%s)" % (resolved.name, name, name)
        return "repr(self.%s)" % name

    def _pass_through(self, varlist: list) -> str:
        """Generate __getattr__ for unique struct/union sub-member."""
        if not self.allow_attr_passthrough:
            return ''
        def is_struct_or_union(decl):
            if isinstance(decl, (FixedArrayDecl, VarArrayDecl)):
                return False
            type_name = _decl_type_name(decl)
            resolved = self.name_dict.get(type_name)
            if isinstance(resolved, (StructDef, UnionDef)):
                return True
            if isinstance(resolved, TypeDef):
                return is_struct_or_union_typedef(resolved)
            return False

        def is_struct_or_union_typedef(td):
            inner_name = _decl_type_name(td.declaration)
            resolved = self.name_dict.get(inner_name)
            if isinstance(resolved, (StructDef, UnionDef)):
                return True
            if isinstance(resolved, TypeDef):
                return is_struct_or_union_typedef(resolved)
            return False

        candidates = [v for v in varlist if is_struct_or_union(v)]
        if len(candidates) == 1:
            name = _decl_name(candidates[0])
            return "%sdef __getattr__(self, attr):\n" \
                   "%sreturn getattr(self.%s, attr)\n\n" % (INDENT, INDENT2, name)
        return ''

    def _xdr_decl_str(self, decl: Declaration) -> str:
        """Return XDR source string for a declaration (for comments)."""
        if isinstance(decl, VoidDecl):
            return 'void;'
        elif isinstance(decl, SimpleDecl):
            return '%s %s;' % (_type_name(decl.type_spec), decl.name)
        elif isinstance(decl, FixedArrayDecl):
            return '%s %s[%s];' % (_type_name(decl.type_spec), decl.name, decl.size)
        elif isinstance(decl, VarArrayDecl):
            ms = decl.max_size or ''
            return '%s %s<%s>;' % (_type_name(decl.type_spec), decl.name, ms)
        elif isinstance(decl, OpaqueFixedDecl):
            return 'opaque %s[%s];' % (decl.name, decl.size)
        elif isinstance(decl, OpaqueVarDecl):
            ms = decl.max_size or ''
            return 'opaque %s<%s>;' % (decl.name, ms)
        elif isinstance(decl, StringDecl):
            ms = decl.max_size or ''
            return 'string %s<%s>;' % (decl.name, ms)
        elif isinstance(decl, PointerDecl):
            return '%s *%s;' % (_type_name(decl.type_spec), decl.name)
        return '???'

    # ---- Pack methods ----

    def _gen_pack(self, defn) -> str:
        if isinstance(defn, EnumDef):
            return self._gen_enum_pack(defn)
        elif isinstance(defn, StructDef):
            return self._gen_struct_pack(defn)
        elif isinstance(defn, UnionDef):
            return self._gen_union_pack(defn)
        elif isinstance(defn, TypeDef):
            return self._gen_typedef_pack(defn)
        return ''

    def _get_filter(self, name: str) -> str:
        if self.use_filters:
            return "%sif hasattr(self, 'filter_%s'):\n" \
                   "%sdata = getattr(self, 'filter_%s')(data)\n" % \
                   (INDENT2, name, INDENT3, name)
        return ''

    def _gen_enum_pack(self, defn: EnumDef) -> str:
        out = "%sdef pack_%s(self, data):\n" % (INDENT, defn.name)
        out += self._get_filter(defn.name)
        varlist = ', '.join(['const.%s' % ec.name for ec in defn.body])
        out += "%sif self.check_enum and data not in [%s]:\n" % (INDENT2, varlist)
        out += "%sraise XDRError('value=%%s not in enum %s' %% data)\n" % (INDENT3, defn.name)
        out += "%sself.pack_int(data)\n" % INDENT2
        return out

    def _gen_struct_pack(self, defn: StructDef) -> str:
        out = "%sdef pack_%s(self, data):\n" % (INDENT, defn.name)
        out += self._get_filter(defn.name)
        for d in defn.body:
            out += self._pack_member(d, INDENT2, 'data')
        return out

    def _gen_union_pack(self, defn: UnionDef) -> str:
        out = "%sdef pack_%s(self, data):\n" % (INDENT, defn.name)
        out += self._get_filter(defn.name)
        # Pack discriminant
        discrim_name = _decl_name(defn.discriminant)
        out += self._pack_member(defn.discriminant, INDENT2, 'data')
        # Cases
        first = ''
        for cs in defn.cases:
            cases_str = ' or '.join(
                ['data.%s == %s' % (discrim_name, _fullname(cv)) for cv in cs.case_values])
            out += "%s%sif %s:\n" % (INDENT2, first, cases_str)
            out += self._pack_member(cs.declaration, INDENT3, 'data')
            first = 'el'
        # Default
        out += "%selse:\n" % INDENT2
        if defn.default_arm is not None and not isinstance(defn.default_arm, VoidDecl):
            out += self._pack_member(defn.default_arm, INDENT3, 'data')
        elif defn.default_arm is not None:
            out += "%spass\n" % INDENT3
        else:
            out += "%sraise XDRError('bad switch=%%s' %% data.%s)\n" % (INDENT3, discrim_name)
        return out

    def _gen_typedef_pack(self, defn: TypeDef) -> str:
        decl = defn.declaration
        name = _decl_name(decl)
        if not name:
            return ''

        # Simple non-array typedef -> alias
        if isinstance(decl, SimpleDecl):
            type_name = _type_name(decl.type_spec)
            return "%spack_%s = pack_%s\n" % (INDENT, name, type_name)

        # Pointer -> variable array with max 1
        if isinstance(decl, PointerDecl):
            type_name = _type_name(decl.type_spec)
            out = "\n%sdef pack_%s(self, data):\n" % (INDENT, name)
            out += self._get_filter(name)
            out += "%sif len(data) > 1 and self.check_array:\n" % INDENT2
            out += "%sraise XDRError('array length too long for %s')\n" % (INDENT3, name)
            out += "%sself.pack_array(data, self.pack_%s)\n" % (INDENT2, type_name)
            return out

        # String typedef
        if isinstance(decl, StringDecl):
            out = "\n%sdef pack_%s(self, data):\n" % (INDENT, name)
            out += self._get_filter(name)
            if decl.max_size:
                out += "%sself.pack_string(data)\n" % INDENT2
            else:
                out += "%sself.pack_string(data)\n" % INDENT2
            return out

        # Opaque typedef
        if isinstance(decl, OpaqueFixedDecl):
            out = "\n%sdef pack_%s(self, data):\n" % (INDENT, name)
            out += self._get_filter(name)
            out += "%sself.pack_fopaque(%s, data)\n" % (INDENT2, _fullname(decl.size))
            return out
        if isinstance(decl, OpaqueVarDecl):
            out = "\n%sdef pack_%s(self, data):\n" % (INDENT, name)
            out += self._get_filter(name)
            out += "%sself.pack_opaque(data)\n" % INDENT2
            return out

        # Array typedef
        if isinstance(decl, FixedArrayDecl):
            type_name = _type_name(decl.type_spec)
            out = "\n%sdef pack_%s(self, data):\n" % (INDENT, name)
            out += self._get_filter(name)
            out += "%sself.pack_farray(%s, data, self.pack_%s)\n" % (
                INDENT2, _fullname(decl.size), type_name)
            return out
        if isinstance(decl, VarArrayDecl):
            type_name = _type_name(decl.type_spec)
            out = "\n%sdef pack_%s(self, data):\n" % (INDENT, name)
            out += self._get_filter(name)
            if decl.max_size:
                out += "%sif len(data) > %s and self.check_array:\n" % (
                    INDENT2, _fullname(decl.max_size))
                out += "%sraise XDRError('array length too long for %s')\n" % (INDENT3, name)
            out += "%sself.pack_array(data, self.pack_%s)\n" % (INDENT2, type_name)
            return out

        return ''

    def _pack_member(self, decl: Declaration, prefix: str, data: str) -> str:
        """Generate pack code for a struct/union member."""
        if isinstance(decl, VoidDecl):
            return '%spass\n' % prefix
        name = _decl_name(decl)
        check = "%sif %s.%s is None:\n%s%sraise TypeError('%s.%s == None')\n" % (
            prefix, data, name, prefix, INDENT, data, name)

        if isinstance(decl, SimpleDecl):
            type_name = _type_name(decl.type_spec)
            # Check if it's an inline struct/union/enum
            if isinstance(decl.type_spec, InlineStructType):
                return check + self._pack_inline_struct(decl.type_spec.body, prefix, '%s.%s' % (data, name))
            elif isinstance(decl.type_spec, InlineUnionType):
                return check + '%sself.pack_%s(%s.%s)\n' % (prefix, name, data, name)
            elif isinstance(decl.type_spec, InlineEnumType):
                return check + self._pack_inline_enum(decl.type_spec.body, prefix, '%s.%s' % (data, name), name)
            return check + "%sself.pack_%s(%s.%s)\n" % (prefix, type_name, data, name)

        elif isinstance(decl, FixedArrayDecl):
            type_name = _type_name(decl.type_spec)
            if type_name == 'opaque':
                return check + "%sself.pack_fopaque(%s, %s.%s)\n" % (
                    prefix, _fullname(decl.size), data, name)
            return check + "%sself.pack_farray(%s, %s.%s, self.pack_%s)\n" % (
                prefix, _fullname(decl.size), data, name, type_name)

        elif isinstance(decl, VarArrayDecl):
            type_name = _type_name(decl.type_spec)
            out = check
            if decl.max_size:
                out += "%sif len(%s.%s) > %s and self.check_array:\n" % (
                    prefix, data, name, _fullname(decl.max_size))
                out += "%s%sraise XDRError('array length too long for %s.%s')\n" % (
                    prefix, INDENT, data, name)
            out += "%sself.pack_array(%s.%s, self.pack_%s)\n" % (prefix, data, name, type_name)
            return out

        elif isinstance(decl, OpaqueFixedDecl):
            return check + "%sself.pack_fopaque(%s, %s.%s)\n" % (
                prefix, _fullname(decl.size), data, name)

        elif isinstance(decl, OpaqueVarDecl):
            out = check
            if decl.max_size:
                out += "%sif len(%s.%s) > %s and self.check_array:\n" % (
                    prefix, data, name, _fullname(decl.max_size))
                out += "%s%sraise XDRError('array length too long for %s.%s')\n" % (
                    prefix, INDENT, data, name)
            out += "%sself.pack_opaque(%s.%s)\n" % (prefix, data, name)
            return out

        elif isinstance(decl, StringDecl):
            out = check
            if decl.max_size:
                out += "%sif len(%s.%s) > %s and self.check_array:\n" % (
                    prefix, data, name, _fullname(decl.max_size))
                out += "%s%sraise XDRError('array length too long for %s.%s')\n" % (
                    prefix, INDENT, data, name)
            out += "%sself.pack_string(%s.%s)\n" % (prefix, data, name)
            return out

        elif isinstance(decl, PointerDecl):
            type_name = _type_name(decl.type_spec)
            out = check
            out += "%sif len(%s.%s) > 1 and self.check_array:\n" % (prefix, data, name)
            out += "%s%sraise XDRError('array length too long for %s.%s')\n" % (prefix, INDENT, data, name)
            out += "%sself.pack_array(%s.%s, self.pack_%s)\n" % (prefix, data, name, type_name)
            return out

        return ''

    def _pack_inline_struct(self, body, prefix, data):
        out = ''
        for d in body:
            out += self._pack_member(d, prefix, data)
        return out

    def _pack_inline_enum(self, body, prefix, data, name):
        varlist = ', '.join(['const.%s' % ec.name for ec in body])
        out = "%sif self.check_enum and %s not in [%s]:\n" % (prefix, data, varlist)
        out += "%s%sraise XDRError('value=%%s not in enum %s' %% %s)\n" % (prefix, INDENT, name, data)
        out += "%sself.pack_int(%s)\n" % (prefix, data)
        return out

    # ---- Unpack methods ----

    def _gen_unpack(self, defn) -> str:
        if isinstance(defn, EnumDef):
            return self._gen_enum_unpack(defn)
        elif isinstance(defn, StructDef):
            return self._gen_struct_unpack(defn)
        elif isinstance(defn, UnionDef):
            return self._gen_union_unpack(defn)
        elif isinstance(defn, TypeDef):
            return self._gen_typedef_unpack(defn)
        return ''

    def _get_unpack_filter(self, name: str) -> str:
        if self.use_filters:
            return "%sif hasattr(self, 'filter_%s'):\n" \
                   "%sdata = getattr(self, 'filter_%s')(data)\n" % \
                   (INDENT2, name, INDENT3, name)
        return ''

    def _gen_enum_unpack(self, defn: EnumDef) -> str:
        out = "%sdef unpack_%s(self):\n" % (INDENT, defn.name)
        out += "%sdata = self.unpack_int()\n" % INDENT2
        varlist = ', '.join(['const.%s' % ec.name for ec in defn.body])
        out += "%sif self.check_enum and data not in [%s]:\n" % (INDENT2, varlist)
        out += "%sraise XDRError('value=%%s not in enum %s' %% data)\n" % (INDENT3, defn.name)
        out += self._get_unpack_filter(defn.name)
        out += "%sreturn data\n" % INDENT2
        return out

    def _gen_struct_unpack(self, defn: StructDef) -> str:
        out = "%sdef unpack_%s(self):\n" % (INDENT, defn.name)
        out += "%sdata = types.%s()\n" % (INDENT2, defn.name)
        for d in defn.body:
            out += self._unpack_member(d, INDENT2, 'data')
        out += self._get_unpack_filter(defn.name)
        out += "%sreturn data\n" % INDENT2
        return out

    def _gen_union_unpack(self, defn: UnionDef) -> str:
        out = "%sdef unpack_%s(self):\n" % (INDENT, defn.name)
        out += "%sdata = types.%s()\n" % (INDENT2, defn.name)
        discrim_name = _decl_name(defn.discriminant)
        out += self._unpack_member(defn.discriminant, INDENT2, 'data')
        first = ''
        for cs in defn.cases:
            cases_str = ' or '.join(
                ['data.%s == %s' % (discrim_name, _fullname(cv)) for cv in cs.case_values])
            out += "%s%sif %s:\n" % (INDENT2, first, cases_str)
            out += self._unpack_member(cs.declaration, INDENT3, 'data')
            first = 'el'
        out += "%selse:\n" % INDENT2
        if defn.default_arm is not None and not isinstance(defn.default_arm, VoidDecl):
            out += self._unpack_member(defn.default_arm, INDENT3, 'data')
        elif defn.default_arm is not None:
            out += "%spass\n" % INDENT3
        else:
            out += "%sraise XDRError('bad switch=%%s' %% data.%s)\n" % (INDENT3, discrim_name)
        out += self._get_unpack_filter(defn.name)
        out += "%sreturn data\n" % INDENT2
        return out

    def _gen_typedef_unpack(self, defn: TypeDef) -> str:
        decl = defn.declaration
        name = _decl_name(decl)
        if not name:
            return ''

        if isinstance(decl, SimpleDecl):
            type_name = _type_name(decl.type_spec)
            return "%sunpack_%s = unpack_%s\n" % (INDENT, name, type_name)

        if isinstance(decl, PointerDecl):
            type_name = _type_name(decl.type_spec)
            out = "%sdef unpack_%s(self):\n" % (INDENT, name)
            out += "%sdata = self.unpack_array(self.unpack_%s)\n" % (INDENT2, type_name)
            out += "%sif len(data) > 1 and self.check_array:\n" % INDENT2
            out += "%sraise XDRError('array length too long for %s')\n" % (INDENT3, name)
            out += self._get_unpack_filter(name)
            out += "%sreturn data\n" % INDENT2
            return out

        if isinstance(decl, StringDecl):
            out = "%sdef unpack_%s(self):\n" % (INDENT, name)
            out += "%sdata = self.unpack_string()\n" % INDENT2
            out += self._get_unpack_filter(name)
            out += "%sreturn data\n" % INDENT2
            return out

        if isinstance(decl, OpaqueFixedDecl):
            out = "%sdef unpack_%s(self):\n" % (INDENT, name)
            out += "%sdata = self.unpack_fopaque(%s)\n" % (INDENT2, _fullname(decl.size))
            out += self._get_unpack_filter(name)
            out += "%sreturn data\n" % INDENT2
            return out

        if isinstance(decl, OpaqueVarDecl):
            out = "%sdef unpack_%s(self):\n" % (INDENT, name)
            out += "%sdata = self.unpack_opaque()\n" % INDENT2
            out += self._get_unpack_filter(name)
            out += "%sreturn data\n" % INDENT2
            return out

        if isinstance(decl, FixedArrayDecl):
            type_name = _type_name(decl.type_spec)
            out = "%sdef unpack_%s(self):\n" % (INDENT, name)
            out += "%sdata = self.unpack_farray(%s, self.unpack_%s)\n" % (
                INDENT2, _fullname(decl.size), type_name)
            out += self._get_unpack_filter(name)
            out += "%sreturn data\n" % INDENT2
            return out

        if isinstance(decl, VarArrayDecl):
            type_name = _type_name(decl.type_spec)
            out = "%sdef unpack_%s(self):\n" % (INDENT, name)
            out += "%sdata = self.unpack_array(self.unpack_%s)\n" % (INDENT2, type_name)
            if decl.max_size:
                out += "%sif len(data) > %s and self.check_array:\n" % (
                    INDENT2, _fullname(decl.max_size))
                out += "%sraise XDRError('array length too long for %s')\n" % (INDENT3, name)
            out += self._get_unpack_filter(name)
            out += "%sreturn data\n" % INDENT2
            return out

        return ''

    def _unpack_member(self, decl: Declaration, prefix: str, data: str) -> str:
        """Generate unpack code for a struct/union member."""
        if isinstance(decl, VoidDecl):
            return '%spass\n' % prefix

        name = _decl_name(decl)

        if isinstance(decl, SimpleDecl):
            type_name = _type_name(decl.type_spec)
            if isinstance(decl.type_spec, InlineStructType):
                out = "%s%s.%s = nullclass()\n" % (prefix, data, name)
                for d in decl.type_spec.body:
                    out += self._unpack_member(d, prefix, '%s.%s' % (data, name))
                return out
            elif isinstance(decl.type_spec, InlineEnumType):
                body = decl.type_spec.body
                out = "%s%s.%s = self.unpack_int()\n" % (prefix, data, name)
                varlist = ', '.join(['const.%s' % ec.name for ec in body])
                out += "%sif self.check_enum and %s.%s not in [%s]:\n" % (prefix, data, name, varlist)
                out += "%s%sraise XDRError('value=%%s not in enum %s' %% %s.%s)\n" % (
                    prefix, INDENT, name, data, name)
                return out
            return "%s%s.%s = self.unpack_%s()\n" % (prefix, data, name, type_name)

        elif isinstance(decl, FixedArrayDecl):
            type_name = _type_name(decl.type_spec)
            if type_name == 'opaque':
                return "%s%s.%s = self.unpack_fopaque(%s)\n" % (
                    prefix, data, name, _fullname(decl.size))
            return "%s%s.%s = self.unpack_farray(%s, self.unpack_%s)\n" % (
                prefix, data, name, _fullname(decl.size), type_name)

        elif isinstance(decl, VarArrayDecl):
            type_name = _type_name(decl.type_spec)
            out = "%s%s.%s = self.unpack_array(self.unpack_%s)\n" % (
                prefix, data, name, type_name)
            if decl.max_size:
                out += "%sif len(%s.%s) > %s and self.check_array:\n" % (
                    prefix, data, name, _fullname(decl.max_size))
                out += "%s%sraise XDRError('array length too long for %s.%s')\n" % (
                    prefix, INDENT, data, name)
            return out

        elif isinstance(decl, OpaqueFixedDecl):
            return "%s%s.%s = self.unpack_fopaque(%s)\n" % (
                prefix, data, name, _fullname(decl.size))

        elif isinstance(decl, OpaqueVarDecl):
            out = "%s%s.%s = self.unpack_opaque()\n" % (prefix, data, name)
            if decl.max_size:
                out += "%sif len(%s.%s) > %s and self.check_array:\n" % (
                    prefix, data, name, _fullname(decl.max_size))
                out += "%s%sraise XDRError('array length too long for %s.%s')\n" % (
                    prefix, INDENT, data, name)
            return out

        elif isinstance(decl, StringDecl):
            out = "%s%s.%s = self.unpack_string()\n" % (prefix, data, name)
            if decl.max_size:
                out += "%sif len(%s.%s) > %s and self.check_array:\n" % (
                    prefix, data, name, _fullname(decl.max_size))
                out += "%s%sraise XDRError('array length too long for %s.%s')\n" % (
                    prefix, INDENT, data, name)
            return out

        elif isinstance(decl, PointerDecl):
            type_name = _type_name(decl.type_spec)
            out = "%s%s.%s = self.unpack_array(self.unpack_%s)\n" % (
                prefix, data, name, type_name)
            out += "%sif len(%s.%s) > 1 and self.check_array:\n" % (prefix, data, name)
            out += "%s%sraise XDRError('array length too long for %s.%s')\n" % (prefix, INDENT, data, name)
            return out

        return ''


##########################################################################
#                       C Code Generator                                 #
##########################################################################

# C type mapping for XDR types
C_TYPE_MAP = {
    'int': 'int32_t',
    'uint': 'uint32_t',
    'hyper': 'int64_t',
    'uhyper': 'uint64_t',
    'float': 'float',
    'double': 'double',
    'quadruple': 'long double',
    'bool': 'bool_t',
}

C_XDR_FUNC_MAP = {
    'int': 'xdr_int32_t',
    'uint': 'xdr_uint32_t',
    'hyper': 'xdr_int64_t',
    'uhyper': 'xdr_uint64_t',
    'float': 'xdr_float',
    'double': 'xdr_double',
    'quadruple': 'xdr_double',
    'bool': 'xdr_bool',
}


def _eval_const(value: str, known: dict) -> int:
    """Evaluate a constant expression to an integer.

    Handles decimal, hex, octal, and simple A+B / A-B arithmetic.
    Raises ValueError if not evaluable.
    """
    value = value.strip()
    if value.startswith('0x') or value.startswith('0X'):
        return int(value, 16)
    if value.startswith('0') and len(value) > 1 and value[1:].isdigit():
        return int(value, 8)
    try:
        return int(value)
    except ValueError:
        pass
    if value in known:
        return known[value]
    for op in ('+', '-'):
        if op in value:
            parts = value.split(op, 1)
            left = _eval_const(parts[0].strip(), known)
            right = _eval_const(parts[1].strip(), known)
            return (left + right) if op == '+' else (left - right)
    raise ValueError("Cannot evaluate: %s" % value)


class CCodeGenerator:
    def __init__(self, spec: Specification, prefix: str):
        self.spec = spec
        self.prefix = prefix
        self.name_dict = {}
        for defn in spec.definitions:
            if isinstance(defn, ConstDef):
                self.name_dict[defn.name] = defn
            elif isinstance(defn, EnumDef):
                self.name_dict[defn.name] = defn
            elif isinstance(defn, StructDef):
                self.name_dict[defn.name] = defn
            elif isinstance(defn, UnionDef):
                self.name_dict[defn.name] = defn
            elif isinstance(defn, TypeDef):
                name = _raw_decl_name(defn.declaration)
                if name:
                    self.name_dict[name] = defn

    def generate(self, output_dir: str):
        h_file = os.path.join(output_dir, self.prefix + '_xdr.h')
        c_file = os.path.join(output_dir, self.prefix + '_xdr.c')

        guard = self.prefix.upper() + '_XDR_H'

        h_lines = []
        c_lines = []

        # Header file
        h_lines.append("/* DO NOT EDIT - generated by xdr_parser.py from %s.x */\n" % self.prefix)
        h_lines.append("/* Apply changes to %s.x instead. */\n\n" % self.prefix)
        h_lines.append("#ifndef %s\n#define %s\n\n" % (guard, guard))
        h_lines.append("#include <stdint.h>\n")
        h_lines.append("#include <stdbool.h>\n")
        h_lines.append("#include <rpc/xdr.h>\n\n")

        # C implementation file
        c_lines.append("/* DO NOT EDIT - generated by xdr_parser.py from %s.x */\n" % self.prefix)
        c_lines.append("/* Apply changes to %s.x instead. */\n\n" % self.prefix)
        c_lines.append('#include "%s_xdr.h"\n\n' % self.prefix)

        for defn in self.spec.definitions:
            h, c = self._gen_c_defn(defn)
            if h:
                h_lines.append(h)
            if c:
                c_lines.append(c)

        h_lines.append("\n#endif /* %s */\n" % guard)

        with open(h_file, 'w') as f:
            f.write(''.join(h_lines))
        with open(c_file, 'w') as f:
            f.write(''.join(c_lines))

    def _c_type(self, ts: TypeSpec) -> str:
        if isinstance(ts, BasicType):
            return C_TYPE_MAP.get(ts.name, ts.name)
        elif isinstance(ts, UnsignedType):
            return C_TYPE_MAP.get(ts.name, 'uint32_t')
        elif isinstance(ts, IdentifierType):
            # typedef struct/enum/union foo foo; is emitted for every named type,
            # so use the bare name everywhere.
            return ts.name
        return 'void'

    def _c_decl_type(self, decl: Declaration) -> str:
        if isinstance(decl, (SimpleDecl, FixedArrayDecl, VarArrayDecl, PointerDecl)):
            return self._c_type(decl.type_spec)
        elif isinstance(decl, (OpaqueFixedDecl, OpaqueVarDecl)):
            return 'char'
        elif isinstance(decl, StringDecl):
            return 'char'
        return 'void'

    def _gen_c_defn(self, defn):
        if isinstance(defn, ConstDef):
            return "#define %s %s\n" % (defn.name, defn.value), ''

        elif isinstance(defn, EnumDef):
            h = "enum %s {\n" % defn.name
            for i, ec in enumerate(defn.body):
                comma = ',' if i < len(defn.body) - 1 else ''
                h += "\t%s = %s%s\n" % (ec.name, ec.value, comma)
            h += "};\n"
            # rpcgen emits typedef so callers use the bare name, not 'enum foo'.
            h += "typedef enum %s %s;\n\n" % (defn.name, defn.name)
            return h, ''

        elif isinstance(defn, StructDef):
            h = "struct %s {\n" % defn.name
            for d in defn.body:
                h += self._c_struct_member(d)
            h += "};\n"
            h += "typedef struct %s %s;\n" % (defn.name, defn.name)
            h += "extern bool_t xdr_%s(XDR *, %s *);\n\n" % (defn.name, defn.name)

            c = "bool_t\nxdr_%s(XDR *xdrs, %s *objp)\n{\n" % (defn.name, defn.name)
            for d in defn.body:
                c += self._c_xdr_member(d, 'objp')
            c += "\treturn TRUE;\n}\n\n"
            return h, c

        elif isinstance(defn, UnionDef):
            # rpcgen names the union sub-field '{typename}_u', not bare 'u'.
            union_u = '%s_u' % defn.name
            h = "struct %s {\n" % defn.name
            discrim_type = self._c_decl_type(defn.discriminant)
            discrim_name = _raw_decl_name(defn.discriminant)
            h += "\t%s %s;\n" % (discrim_type, discrim_name)
            h += "\tunion {\n"
            for cs in defn.cases:
                if not isinstance(cs.declaration, VoidDecl):
                    h += "\t" + self._c_struct_member(cs.declaration)
            if defn.default_arm and not isinstance(defn.default_arm, VoidDecl):
                h += "\t" + self._c_struct_member(defn.default_arm)
            h += "\t} %s;\n" % union_u
            h += "};\n"
            h += "typedef struct %s %s;\n" % (defn.name, defn.name)
            h += "extern bool_t xdr_%s(XDR *, %s *);\n\n" % (defn.name, defn.name)

            c = "bool_t\nxdr_%s(XDR *xdrs, %s *objp)\n{\n" % (defn.name, defn.name)
            c += self._c_xdr_member(defn.discriminant, 'objp')
            c += "\tswitch (objp->%s) {\n" % discrim_name
            for cs in defn.cases:
                for cv in cs.case_values:
                    c += "\tcase %s:\n" % cv
                if isinstance(cs.declaration, VoidDecl):
                    c += "\t\tbreak;\n"
                else:
                    # Union arm: 'objp->{union_u}' is a value, use '.' for members.
                    c += self._c_xdr_member(cs.declaration,
                                            'objp->%s' % union_u, sep='.')
                    c += "\t\tbreak;\n"
            if defn.default_arm is not None:
                c += "\tdefault:\n"
                if isinstance(defn.default_arm, VoidDecl):
                    c += "\t\tbreak;\n"
                else:
                    c += self._c_xdr_member(defn.default_arm,
                                            'objp->%s' % union_u, sep='.')
                    c += "\t\tbreak;\n"
            c += "\t}\n"
            c += "\treturn TRUE;\n}\n\n"
            return h, c

        elif isinstance(defn, TypeDef):
            decl = defn.declaration
            name = _raw_decl_name(decl)
            if not name:
                return '', ''

            if isinstance(decl, SimpleDecl):
                c_type = self._c_type(decl.type_spec)
                type_name = _type_name(decl.type_spec)
                xdr_func = C_XDR_FUNC_MAP.get(type_name, 'xdr_%s' % type_name)
                h = "typedef %s %s;\n" % (c_type, name)
                h += "extern bool_t xdr_%s(XDR *, %s *);\n\n" % (name, name)
                c = "bool_t\nxdr_%s(XDR *xdrs, %s *objp)\n{\n" % (name, name)
                c += "\tif (!%s(xdrs, objp))\n\t\treturn FALSE;\n" % xdr_func
                c += "\treturn TRUE;\n}\n\n"
                return h, c

            elif isinstance(decl, PointerDecl):
                c_type = self._c_type(decl.type_spec)
                type_name = _type_name(decl.type_spec)
                h = "typedef %s *%s;\n" % (c_type, name)
                h += "extern bool_t xdr_%s(XDR *, %s *);\n\n" % (name, name)
                c = "bool_t\nxdr_%s(XDR *xdrs, %s *objp)\n{\n" % (name, name)
                c += "\tif (!xdr_pointer(xdrs, (char **)objp, sizeof(%s), (xdrproc_t)xdr_%s))\n\t\treturn FALSE;\n" % (c_type, type_name)
                c += "\treturn TRUE;\n}\n\n"
                return h, c

            elif isinstance(decl, StringDecl):
                max_s = decl.max_size or '~0'
                h = "typedef char *%s;\n" % name
                h += "extern bool_t xdr_%s(XDR *, %s *);\n\n" % (name, name)
                c = "bool_t\nxdr_%s(XDR *xdrs, %s *objp)\n{\n" % (name, name)
                c += "\tif (!xdr_string(xdrs, objp, %s))\n\t\treturn FALSE;\n" % max_s
                c += "\treturn TRUE;\n}\n\n"
                return h, c

            elif isinstance(decl, OpaqueVarDecl):
                # rpcgen: struct { u_int foo_len; char *foo_val; } foo;
                max_s = decl.max_size or '~0'
                h = "typedef struct {\n\tu_int %s_len;\n\tchar *%s_val;\n} %s;\n" % (
                    name, name, name)
                h += "extern bool_t xdr_%s(XDR *, %s *);\n\n" % (name, name)
                c = "bool_t\nxdr_%s(XDR *xdrs, %s *objp)\n{\n" % (name, name)
                c += "\tif (!xdr_bytes(xdrs, &objp->%s_val, &objp->%s_len, %s))\n\t\treturn FALSE;\n" % (
                    name, name, max_s)
                c += "\treturn TRUE;\n}\n\n"
                return h, c

            elif isinstance(decl, OpaqueFixedDecl):
                # rpcgen: typedef char foo[N]; xdr_foo takes the array by value decay.
                h = "typedef char %s[%s];\n" % (name, decl.size)
                h += "extern bool_t xdr_%s(XDR *, %s);\n\n" % (name, name)
                c = "bool_t\nxdr_%s(XDR *xdrs, %s objp)\n{\n" % (name, name)
                c += "\tif (!xdr_opaque(xdrs, objp, %s))\n\t\treturn FALSE;\n" % decl.size
                c += "\treturn TRUE;\n}\n\n"
                return h, c

            elif isinstance(decl, FixedArrayDecl):
                c_type = self._c_type(decl.type_spec)
                type_name = _type_name(decl.type_spec)
                xdr_func = C_XDR_FUNC_MAP.get(type_name, 'xdr_%s' % type_name)
                h = "typedef %s %s[%s];\n" % (c_type, name, decl.size)
                h += "extern bool_t xdr_%s(XDR *, %s);\n\n" % (name, name)
                c = "bool_t\nxdr_%s(XDR *xdrs, %s objp)\n{\n" % (name, name)
                c += "\tif (!xdr_vector(xdrs, (char *)objp, %s, sizeof(%s), (xdrproc_t)%s))\n\t\treturn FALSE;\n" % (
                    decl.size, c_type, xdr_func)
                c += "\treturn TRUE;\n}\n\n"
                return h, c

            elif isinstance(decl, VarArrayDecl):
                # rpcgen: struct { u_int foo_len; T *foo_val; } foo;
                c_type = self._c_type(decl.type_spec)
                type_name = _type_name(decl.type_spec)
                xdr_func = C_XDR_FUNC_MAP.get(type_name, 'xdr_%s' % type_name)
                max_s = decl.max_size or '~0'
                h = "typedef struct {\n\tu_int %s_len;\n\t%s *%s_val;\n} %s;\n" % (
                    name, c_type, name, name)
                h += "extern bool_t xdr_%s(XDR *, %s *);\n\n" % (name, name)
                c = "bool_t\nxdr_%s(XDR *xdrs, %s *objp)\n{\n" % (name, name)
                c += "\tif (!xdr_array(xdrs, (char **)&objp->%s_val, &objp->%s_len, %s, sizeof(%s), (xdrproc_t)%s))\n\t\treturn FALSE;\n" % (
                    name, name, max_s, c_type, xdr_func)
                c += "\treturn TRUE;\n}\n\n"
                return h, c

        elif isinstance(defn, ProgramDef):
            h = "#define %s %s\n" % (defn.name, defn.program_number)
            for ver in defn.versions:
                h += "#define %s %s\n" % (ver.name, ver.version_number)
                for proc in ver.procedures:
                    h += "#define %s %s\n" % (proc.name, proc.proc_number)
            h += "\n"
            return h, ''

        elif isinstance(defn, PassthroughLine):
            return defn.text + '\n', ''

        return '', ''

    def _c_struct_member(self, decl: Declaration) -> str:
        if isinstance(decl, VoidDecl):
            return ''
        name = _raw_decl_name(decl)
        if isinstance(decl, SimpleDecl):
            c_type = self._c_type(decl.type_spec)
            return "\t%s %s;\n" % (c_type, name)
        elif isinstance(decl, FixedArrayDecl):
            c_type = self._c_type(decl.type_spec)
            return "\t%s %s[%s];\n" % (c_type, name, decl.size)
        elif isinstance(decl, VarArrayDecl):
            # rpcgen: struct { u_int name_len; T *name_val; } name;
            c_type = self._c_type(decl.type_spec)
            return "\tstruct { u_int %s_len; %s *%s_val; } %s;\n" % (name, c_type, name, name)
        elif isinstance(decl, OpaqueFixedDecl):
            return "\tchar %s[%s];\n" % (name, decl.size)
        elif isinstance(decl, OpaqueVarDecl):
            # rpcgen: struct { u_int name_len; char *name_val; } name;
            return "\tstruct { u_int %s_len; char *%s_val; } %s;\n" % (name, name, name)
        elif isinstance(decl, StringDecl):
            return "\tchar *%s;\n" % name
        elif isinstance(decl, PointerDecl):
            c_type = self._c_type(decl.type_spec)
            return "\t%s *%s;\n" % (c_type, name)
        return ''

    def _c_xdr_member(self, decl: Declaration, obj: str, sep: str = '->') -> str:
        """Generate an XDR encode/decode call for one struct or union member.

        obj  -- C expression for the containing object.  A pointer when
                sep='->'; a union-member value (accessed via prior '->')
                when sep='.'.
        sep  -- '->': obj is a pointer (normal struct / discriminant path).
                '.': obj is a union value (union-arm path: objp->{name}_u).
        """
        if isinstance(decl, VoidDecl):
            return ''
        name = _raw_decl_name(decl)
        accessor = '%s%s%s' % (obj, sep, name)

        if isinstance(decl, SimpleDecl):
            type_name = _type_name(decl.type_spec)
            xdr_func = C_XDR_FUNC_MAP.get(type_name)
            if xdr_func:
                return "\tif (!%s(xdrs, &%s))\n\t\treturn FALSE;\n" % (xdr_func, accessor)
            return "\tif (!xdr_%s(xdrs, &%s))\n\t\treturn FALSE;\n" % (type_name, accessor)

        elif isinstance(decl, OpaqueFixedDecl):
            return "\tif (!xdr_opaque(xdrs, %s, %s))\n\t\treturn FALSE;\n" % (accessor, decl.size)

        elif isinstance(decl, OpaqueVarDecl):
            # accessor is e.g. 'objp->data'; sub-fields are 'objp->data.data_val'.
            max_s = decl.max_size or '~0'
            return "\tif (!xdr_bytes(xdrs, &%s.%s_val, &%s.%s_len, %s))\n\t\treturn FALSE;\n" % (
                accessor, name, accessor, name, max_s)

        elif isinstance(decl, StringDecl):
            max_s = decl.max_size or '~0'
            return "\tif (!xdr_string(xdrs, &%s, %s))\n\t\treturn FALSE;\n" % (accessor, max_s)

        elif isinstance(decl, FixedArrayDecl):
            type_name = _type_name(decl.type_spec)
            xdr_func = C_XDR_FUNC_MAP.get(type_name, 'xdr_%s' % type_name)
            c_type = self._c_type(decl.type_spec)
            return "\tif (!xdr_vector(xdrs, (char *)%s, %s, sizeof(%s), (xdrproc_t)%s))\n\t\treturn FALSE;\n" % (
                accessor, decl.size, c_type, xdr_func)

        elif isinstance(decl, VarArrayDecl):
            # accessor is e.g. 'objp->arr'; sub-fields are 'objp->arr.arr_val'.
            type_name = _type_name(decl.type_spec)
            xdr_func = C_XDR_FUNC_MAP.get(type_name, 'xdr_%s' % type_name)
            c_type = self._c_type(decl.type_spec)
            max_s = decl.max_size or '~0'
            return "\tif (!xdr_array(xdrs, (char **)&%s.%s_val, &%s.%s_len, %s, sizeof(%s), (xdrproc_t)%s))\n\t\treturn FALSE;\n" % (
                accessor, name, accessor, name, max_s, c_type, xdr_func)

        elif isinstance(decl, PointerDecl):
            type_name = _type_name(decl.type_spec)
            return "\tif (!xdr_pointer(xdrs, (char **)&%s, sizeof(%s), (xdrproc_t)xdr_%s))\n\t\treturn FALSE;\n" % (
                accessor, self._c_type(decl.type_spec), type_name)

        return ''


##########################################################################
#                        Names Code Generator                            #
##########################################################################

class NamesGenerator:
    """Generate integer-to-name lookup tables from XDR enum/const definitions.

    For each group of constants sharing a common prefix (e.g., NFS4ERR_,
    FATTR4_, OP_, CB_), emits a lookup function that maps integer values to
    their string names.  Emits _MAX constants (e.g., OP_MAX) for tracked
    groups that request them.

    For C (--lang c --names): emits {prefix}_names.h and {prefix}_names.c.
    For Python (--lang python --names): emits {prefix}_names.py.
    """

    # (prefix, C_func_name, max_const_or_None, exclusive, exclude_from_max_or_None)
    # Listed longest-match first so OP_ does not shadow OP_CB_ etc.
    #
    # exclusive: True  -> _MAX = highest_val + 1  (array size, e.g. OP_MAX)
    #            False -> _MAX = highest_val       (inclusive, e.g. FATTR4_ATTRIBUTE_MAX)
    #
    # exclude_from_max: names excluded from the _MAX calculation
    # (but still included in the lookup table).
    TRACKED = [
        ('NFS4ERR_',  'nfs4_err_name',    None,                   True,  None),
        # FATTR4_ATTRIBUTE_MAX is an inclusive max (highest valid attr bit).
        ('FATTR4_',   'fattr4_name',       'FATTR4_ATTRIBUTE_MAX', False, None),
        ('OP_CB_',    'nfs4_cb_name',      None,                   True,  None),
        # OP_ILLEGAL = 10044 is in the enum but the dispatch table only
        # covers real protocol ops; exclude it from the OP_MAX bound.
        ('OP_',       'nfs4_op_name',      'OP_MAX',               True,
         frozenset({'OP_ILLEGAL', 'OP_CB_ILLEGAL'})),
    ]

    def __init__(self, spec: Specification, prefix: str):
        self.spec = spec
        self.prefix = prefix

        # Collect all named integer constants from enums and const defs.
        self.constants = {}  # name -> int
        for defn in spec.definitions:
            if isinstance(defn, ConstDef):
                try:
                    self.constants[defn.name] = _eval_const(defn.value, self.constants)
                except (ValueError, KeyError):
                    pass
            elif isinstance(defn, EnumDef):
                for ec in defn.body:
                    try:
                        self.constants[ec.name] = _eval_const(ec.value, self.constants)
                    except (ValueError, KeyError):
                        pass

    def _build_groups(self):
        """Return {prefix: sorted[(name, val)]} for tracked prefixes."""
        groups = {}
        prefixes = [entry[0] for entry in self.TRACKED]
        for name, val in self.constants.items():
            for pfx in prefixes:
                if name.startswith(pfx):
                    groups.setdefault(pfx, []).append((name, val))
                    break
        for pfx in groups:
            groups[pfx].sort(key=lambda x: x[1])
        return groups

    def _max_val_for_group(self, pfx: str, entries: list) -> int:
        """Return the highest value in entries, honouring exclude_from_max."""
        exclude = None
        for entry in self.TRACKED:
            if entry[0] == pfx:
                exclude = entry[4]
                break
        if exclude:
            filtered = [v for name, v in entries if name not in exclude]
        else:
            filtered = [v for _, v in entries]
        return max(filtered) if filtered else 0

    def _max_const_val(self, pfx: str, entries: list) -> int:
        """Return the value to emit for the _MAX constant.

        exclusive=True:  max_val + 1  (array size)
        exclusive=False: max_val      (inclusive maximum)
        """
        max_val = self._max_val_for_group(pfx, entries)
        exclusive = True
        for entry in self.TRACKED:
            if entry[0] == pfx:
                exclusive = entry[3]
                break
        return max_val + 1 if exclusive else max_val

    def generate_c(self, output_dir: str):
        h_file = os.path.join(output_dir, self.prefix + '_names.h')
        c_file = os.path.join(output_dir, self.prefix + '_names.c')

        guard = self.prefix.upper() + '_NAMES_H'
        groups = self._build_groups()

        h_lines = []
        c_lines = []

        h_lines.append("/* DO NOT EDIT - generated by xdr_parser.py from %s.x */\n" % self.prefix)
        h_lines.append("/* Apply changes to %s.x instead. */\n\n" % self.prefix)
        h_lines.append("#ifndef %s\n#define %s\n\n" % (guard, guard))
        h_lines.append("#include <stdint.h>\n\n")

        c_lines.append("/* DO NOT EDIT - generated by xdr_parser.py from %s.x */\n" % self.prefix)
        c_lines.append("/* Apply changes to %s.x instead. */\n\n" % self.prefix)
        c_lines.append('#include "%s_names.h"\n\n' % self.prefix)

        for pfx, func_name, max_const, _excl, _excl2 in self.TRACKED:
            if pfx not in groups:
                continue
            entries = groups[pfx]
            if not entries:
                continue

            min_val = entries[0][1]
            max_val = entries[-1][1]

            if max_const:
                h_lines.append("#define %s (%d)\n" % (
                    max_const, self._max_const_val(pfx, entries)))
            h_lines.append("const char *%s(uint32_t val);\n\n" % func_name)

            # Dense array when >= 50% fill and range fits in 4096 slots.
            range_size = max_val - min_val + 1
            density = len(entries) / range_size if range_size > 0 else 0
            use_array = (density >= 0.5) and (range_size <= 4096)

            if use_array:
                table = ['NULL'] * range_size
                for entry_name, val in entries:
                    idx = val - min_val
                    if 0 <= idx < range_size:
                        table[idx] = '"%s"' % entry_name
                c_lines.append("static const char * const %s_names[] = {\n" % func_name)
                for i, s in enumerate(table):
                    c_lines.append("\t%s,\n" % s)
                c_lines.append("};\n\n")
                c_lines.append("const char *\n%s(uint32_t val)\n{\n" % func_name)
                if min_val > 0:
                    c_lines.append("\tif (val < %du)\n\t\treturn NULL;\n" % min_val)
                c_lines.append("\tif (val > %du)\n\t\treturn NULL;\n" % max_val)
                c_lines.append("\treturn %s_names[val - %du];\n" % (func_name, min_val))
                c_lines.append("}\n\n")
            else:
                # Sparse: switch statement.
                c_lines.append("const char *\n%s(uint32_t val)\n{\n" % func_name)
                c_lines.append("\tswitch (val) {\n")
                seen = set()
                for entry_name, val in entries:
                    if val not in seen:
                        c_lines.append("\tcase %du: return \"%s\";\n" % (val, entry_name))
                        seen.add(val)
                c_lines.append("\tdefault: return NULL;\n")
                c_lines.append("\t}\n")
                c_lines.append("}\n\n")

        h_lines.append("#endif /* %s */\n" % guard)

        with open(h_file, 'w') as f:
            f.write(''.join(h_lines))
        with open(c_file, 'w') as f:
            f.write(''.join(c_lines))

    def generate_python(self, output_dir: str):
        py_file = os.path.join(output_dir, self.prefix + '_names.py')
        groups = self._build_groups()

        lines = []
        lines.append("# DO NOT EDIT - generated by xdr_parser.py from %s.x\n" % self.prefix)
        lines.append("# Apply changes to %s.x instead.\n\n" % self.prefix)

        for pfx, func_name, max_const, _excl, _excl2 in self.TRACKED:
            if pfx not in groups:
                continue
            entries = groups[pfx]
            if not entries:
                continue

            if max_const:
                lines.append("%s = %d\n" % (
                    max_const, self._max_const_val(pfx, entries)))

            # Dict name is the capitalized version of the func without trailing '_name'.
            dict_name = func_name.upper()
            if dict_name.endswith('_NAME'):
                dict_name = dict_name[:-5] + 'S'
            lines.append("%s = {\n" % dict_name)
            seen = set()
            for entry_name, val in entries:
                if val not in seen:
                    lines.append("    %d: '%s',\n" % (val, entry_name))
                    seen.add(val)
            lines.append("}\n\n")

        with open(py_file, 'w') as f:
            f.write(''.join(lines))


##########################################################################
#                         CLI Entry Point                                #
##########################################################################

def main():
    parser = argparse.ArgumentParser(
        description='XDR parser and code generator (RFC 4506/5531)')
    parser.add_argument('input', help='Input XDR (.x) file')
    parser.add_argument('--lang', choices=['python', 'c'], default='python',
                       help='Target language (default: python)')
    parser.add_argument('--names', action='store_true',
                       help='Generate name-lookup tables instead of XDR code')
    parser.add_argument('--output-dir', default='.',
                       help='Output directory (default: current directory)')
    parser.add_argument('--prefix',
                       help='Prefix for output filenames (default: input basename)')
    args = parser.parse_args()

    # Read input
    try:
        with open(args.input, 'r') as f:
            text = f.read()
    except IOError as e:
        print("Error: %s" % e, file=sys.stderr)
        sys.exit(1)

    # Determine prefix
    prefix = args.prefix
    if not prefix:
        prefix = os.path.basename(args.input)
        if prefix.endswith('.x'):
            prefix = prefix[:-2]

    # Ensure output directory exists
    if args.output_dir != '.' and not os.path.isdir(args.output_dir):
        os.makedirs(args.output_dir)

    # Lex
    try:
        lexer = Lexer(text)
    except LexerError as e:
        print("Lexer error: %s" % e, file=sys.stderr)
        sys.exit(1)

    # Parse
    try:
        p = Parser(lexer.tokens)
        spec = p.parse()
    except ParseError as e:
        print("Parse error: %s" % e, file=sys.stderr)
        sys.exit(1)

    # Generate
    if args.names:
        gen = NamesGenerator(spec, prefix)
        if args.lang == 'c':
            gen.generate_c(args.output_dir)
            print("Generated %s_names.h, %s_names.c in %s" % (
                prefix, prefix, args.output_dir))
        else:
            gen.generate_python(args.output_dir)
            print("Generated %s_names.py in %s" % (prefix, args.output_dir))
    elif args.lang == 'python':
        gen = PythonCodeGenerator(spec, prefix)
        gen.generate(args.output_dir)
        print("Generated %s_const.py, %s_type.py, %s_pack.py in %s" % (
            prefix, prefix, prefix, args.output_dir))
    elif args.lang == 'c':
        gen = CCodeGenerator(spec, prefix)
        gen.generate(args.output_dir)
        print("Generated %s_xdr.h, %s_xdr.c in %s" % (
            prefix, prefix, args.output_dir))


if __name__ == '__main__':
    main()
