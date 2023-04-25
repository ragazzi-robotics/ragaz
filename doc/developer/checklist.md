# Ragaz Builtins Implementation

This is a checklist to serve as roadmap to port most of the Python builtins presents in CPython as well as new 
features necessary to systems development. Items checked with X are those already present in Ragaz.

## Operators

### Arithmetic Operators

- [x] Addition (**+**)
- [x] Subtraction (**-**)
- [x] Multiplication (**\***)
- [x] Division (**/**)
- [x] Modulus (**%**)
- [x] Floor division (**//**)
- [x] Exponentiation (**\*\***)

### Comparison Operators

- [x] Equal (**==**)
- [x] Not equal (**!=**)
- [x] Greater than (**>**)
- [x] Less than (**<**)
- [x] Greater than or equal to (**>=**)
- [x] Less than or equal to (**<=**)

### Logical Operators

- [x] And (**and**)
- [x] Or (**or**)
- [x] Not (**not**)

### Bitwise Operators

- [x] And (**&**)
- [x] Or (**|**)
- [x] XOr (**^**)
- [x] Not (**~**)
- [x] Shift to left (**<<**)
- [x] Shift to right (**>>**)

### Other Operators

- [x] Is (**is**): partially, used only with **None**
- [x] In (**in**)

## Types

- [x] int
- [x] float
- [x] str
- [x] iter
- [x] list
- [x] set
- [x] dict
- [x] function

## Functions

Neither all functions bellow will be ported to Ragaz. Some of them are valid only in an interpreter context, which is 
not the case of Ragaz. They are in the list because weren't analysed individually yet.

- [x] abs()
- [ ] aiter()
- [x] all()
- [x] any()
- [ ] anext()
- [ ] ascii()
- [x] bin()
- [x] bool()
- [ ] breakpoint()
- [ ] bytearray()
- [ ] bytes()
- [ ] callable()
- ~~[ ] chr()~~ : not implemented because type **Char** already is represented in ascii or character between single quotes.
- [ ] classmethod()
- [ ] compile()
- [ ] complex()
- [ ] delattr()
- [x] dict()
- [ ] dir()
- [x] divmod()
- [x] enumerate()
- [ ] eval()
- [ ] exec()
- [x] filter()
- [x] float()
- [ ] format()
- [ ] frozenset()
- [ ] getattr()
- [ ] globals()
- [ ] hasattr()
- [x] hash()
- [ ] help()
- [x] hex()
- [ ] id()
- [ ] input()
- [x] int()
- [x] isinstance()
- [ ] issubclass()
- [x] iter()
- [x] len()
- [x] list()
- [ ] locals()
- [x] map()
- [x] max()
- [ ] memoryview()
- [x] min()
- [ ] next()
- [ ] object()
- [x] oct()
- [ ] open()
- ~~[ ] ord()~~ : not implemented because type **Char** already is represented in ascii or character between single quotes. 
- [x] pow()
- [x] print()
- [ ] property()
- [x] range()
- [x] repr()
- [x] reversed()
- [x] round()
- [x] set()
- [ ] setattr()
- [ ] slice()
- [x] sorted()
- [ ] staticmethod()
- [x] str()
- [x] sum()
- [ ] super()
- [x] tuple()
- [ ] type()
- [ ] vars()
- [x] zip()
