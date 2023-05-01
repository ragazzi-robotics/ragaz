Hello everyone, I would like to introduce you to a project that I have been working on for 2 years. For those who don't know me, my name is David, I'm a software engineer (MSc) and I've been working with Python and artificial intelligence for a few years.

The name of the project is Ragaz, and it consists of a compiler which I'm writing aimed at meeting requirements that many developers, like me, have always wanted in the Pythonic world as such as:

- Runtime speed equal to or close to languages like C/C++ or Rust.
- Compiling a Python project to pure executable code (using [LLVM](https://www.infoworld.com/article/3247799/what-is-llvm-the-power-behind-swift-rust-clang-and-more.html)) without the need for virtual machines, wrappings, decorators, and other extras to distribute your software.
- Code that runs on multiple processors (because there is no [GIL](https://granulate.io/blog/introduction-to-the-infamous-python-gil/)).
- Rust-like memory management that eliminates garbage collector, improves runtime speed and prevents memory access bugs.

With these requirements already being met in my project, even creating an operating system in a python-like syntax would be feasible, for example.

I made this chart comparing Ragaz's performance with the official version of Python and C/C++. As you can see, the program compiled in Ragaz is dozens of times faster than the default implementation of Python 3.9 and with a speed equal to or close to that of C/C++.

![Benchmarking](https://raw.githubusercontent.com/ragazzi-robotics/ragaz/main/doc/user/pictures/benchmarking.jpg "benchmarking")

However the focus is not only on speed but also on power and safeness, as the goal is not just to develop a language to accelerate scripts, but a general purpose language, allowing the creation of a general range of applications from simple scripts to complex systems.
As a proof of concept, the built-in functions and types themselves are all already written in Ragaz (look [this](https://github.com/ragazzi-robotics/ragaz/blob/main/ragaz/core/__builtins__.zz)), and soon, the entire standard library will also be written in Ragaz.

The good news is that despite these qualities and even Ragaz being a dialect of Python, the code is very similar to standard python, requiring few changes to compile it. It's like you have the power of C/C++ in a pythonic code which is relatively easier to read and maintain.

I'll release an Alpha version soon, but as I'm working alone on this, I'd appreciate any help available to speed this step up, whether it's contributing with reporting bugs, writing code or documentation, etc, or contributing financially with donations (so I can dedicate myself to 100% to him, and not dividing my attention with other projects).
Companies that also want to sponsor the project will have their brands published on the official page, if they prefer.

I am pleased to invite you to access the project page on GitHub to learn a little about the project and see how to contribute:

https://github.com/ragazzi-robotics/ragaz
